import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from .models import Cluster, Node, NodeOperation
from .forms import (
    ClusterForm, NodeForm, RestartServiceForm, MachineConfigForm,
    ClusterBootstrapForm, NodeApplyConfigForm,
)
from .talosctl import TalosctlRunner
from .mixins import operator_required, admin_required


def _parse_talosctl_table(output):
    """Parse talosctl table output into (headers, rows) where each row is a dict."""
    lines = [l for l in output.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        return [], []
    headers = re.split(r'\s{2,}', lines[0].strip())
    rows = []
    for line in lines[1:]:
        parts = re.split(r'\s{2,}', line.strip(), maxsplit=len(headers) - 1)
        while len(parts) < len(headers):
            parts.append('')
        rows.append(dict(zip(headers, parts)))
    return headers, rows


# ─── Dashboard ───────────────────────────────────────────────────────────────

@login_required
def overview(request):
    clusters = Cluster.objects.filter(is_active=True).prefetch_related('nodes')
    recent_ops = NodeOperation.objects.select_related('node__cluster', 'initiated_by').order_by('-started_at')[:10]
    return render(request, 'dashboard/overview.html', {
        'clusters': clusters,
        'recent_ops': recent_ops,
    })


@login_required
def node_rows_partial(request):
    """HTMX partial: returns only the node table rows for the dashboard auto-refresh."""
    clusters = Cluster.objects.filter(is_active=True).prefetch_related('nodes')
    return render(request, 'dashboard/_node_rows.html', {'clusters': clusters})


# ─── Clusters ────────────────────────────────────────────────────────────────

@login_required
def cluster_list(request):
    clusters = Cluster.objects.filter(is_active=True).prefetch_related('nodes')
    return render(request, 'clusters/cluster_list.html', {'clusters': clusters})


@login_required
def cluster_add(request):
    if not request.user.profile.is_admin:
        messages.error(request, 'Only admins can add clusters.')
        return redirect('clusters:list')

    form = ClusterForm(request.POST or None)
    if form.is_valid():
        cluster = form.save(commit=False)
        cluster.created_by = request.user
        cluster.save()
        messages.success(request, f'Cluster "{cluster.name}" added.')
        return redirect('clusters:detail', pk=cluster.pk)

    return render(request, 'clusters/cluster_form.html', {'form': form, 'action': 'Add'})


@login_required
def cluster_edit(request, pk):
    cluster = get_object_or_404(Cluster, pk=pk)
    if not request.user.profile.is_admin:
        messages.error(request, 'Only admins can edit clusters.')
        return redirect('clusters:detail', pk=pk)

    form = ClusterForm(request.POST or None, instance=cluster)
    if form.is_valid():
        form.save()
        messages.success(request, f'Cluster "{cluster.name}" updated.')
        return redirect('clusters:detail', pk=pk)

    return render(request, 'clusters/cluster_form.html', {'form': form, 'cluster': cluster, 'action': 'Edit'})


@login_required
def cluster_detail(request, pk):
    cluster = get_object_or_404(Cluster, pk=pk)
    nodes = cluster.nodes.all()
    return render(request, 'clusters/cluster_detail.html', {'cluster': cluster, 'nodes': nodes})


@login_required
def download_talosconfig(request, pk):
    cluster = get_object_or_404(Cluster, pk=pk)
    response = HttpResponse(cluster.talosconfig_content, content_type='application/x-yaml')
    response['Content-Disposition'] = f'attachment; filename="talosconfig-{cluster.name}.yaml"'
    return response


@login_required
def download_kubeconfig(request, pk):
    cluster = get_object_or_404(Cluster, pk=pk)
    try:
        with TalosctlRunner(cluster) as t:
            result = t.get_kubeconfig()
        if result['success']:
            response = HttpResponse(result['stdout'], content_type='application/x-yaml')
            response['Content-Disposition'] = f'attachment; filename="kubeconfig-{cluster.name}.yaml"'
            return response
        messages.error(request, f'Failed to get kubeconfig: {result["stderr"]}')
    except Exception as e:
        messages.error(request, f'Error: {e}')
    return redirect('clusters:detail', pk=pk)


@login_required
@require_POST
def cluster_bootstrap_etcd(request, pk):
    """Run talosctl bootstrap on the first control plane node."""
    if not request.user.profile.is_admin:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    cluster = get_object_or_404(Cluster, pk=pk)
    cp_node = cluster.nodes.filter(role=Node.ROLE_CONTROLPLANE).first()
    if not cp_node:
        messages.error(request, 'No control plane node found in this cluster.')
        return redirect('clusters:detail', pk=pk)
    try:
        with TalosctlRunner(cluster) as t:
            result = t.bootstrap(cp_node.ip_address)
        if result['success']:
            messages.success(request, f'Bootstrap sent to {cp_node.ip_address}. etcd is starting.')
        else:
            err = result['stderr'] or result['stdout'] or 'Unknown error'
            messages.error(request, f'Bootstrap failed: {err}')
    except Exception as e:
        messages.error(request, f'Bootstrap error: {e}')
    return redirect('clusters:detail', pk=pk)


@login_required
def cluster_delete(request, pk):
    if not request.user.profile.is_admin:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    cluster = get_object_or_404(Cluster, pk=pk)
    if request.method == 'POST':
        name = cluster.name
        cluster.delete()
        messages.success(request, f'Cluster "{name}" deleted.')
        return redirect('clusters:list')
    return render(request, 'clusters/cluster_confirm_delete.html', {'cluster': cluster})


@login_required
@require_POST
def cluster_refresh(request, pk):
    """Refresh node status from talosctl."""
    cluster = get_object_or_404(Cluster, pk=pk)
    try:
        with TalosctlRunner(cluster) as t:
            members, err = t.get_members()
            if err:
                messages.error(request, f'talosctl error: {err}')
                return redirect('clusters:detail', pk=pk)
            # Fetch k8s version once from the endpoint node (cluster-wide)
            k8s_ver = t.get_k8s_version()
            for m in members:
                ip = m['ip']
                node, _ = Node.objects.get_or_create(cluster=cluster, ip_address=ip)
                if m['hostname']:
                    node.hostname = m['hostname']
                if m['talos_version']:
                    node.talos_version = m['talos_version']
                if m['k8s_version']:
                    node.k8s_version = m['k8s_version']
                elif k8s_ver:
                    node.k8s_version = k8s_ver
                node.role = m['role']
                node.status = 'running'
                node.last_seen = timezone.now()
                node.save(update_fields=['hostname', 'talos_version', 'k8s_version', 'role', 'status', 'last_seen'])
        messages.success(request, f'Cluster refreshed. {len(members)} node(s) found.')
    except Exception as e:
        messages.error(request, f'Refresh failed: {e}')
    return redirect('clusters:detail', pk=pk)


@login_required
def cluster_test_connection(request, pk):
    """Run talosctl version + get members and show raw output for debugging."""
    cluster = get_object_or_404(Cluster, pk=pk)
    results = []
    error = None
    node_ip = cluster.endpoint.split(':')[0]
    try:
        with TalosctlRunner(cluster) as t:
            for label, args in [
                ('version', ['version']),
                ('get members', ['get', 'members', '-o', 'json']),
            ]:
                r = t.run(args, timeout=10)
                results.append({
                    'label': label,
                    'cmd': f'talosctl --talosconfig <tmp> --endpoints {cluster.endpoint} -n {node_ip} {" ".join(args)}',
                    'returncode': r['returncode'],
                    'stdout': r['stdout'],
                    'stderr': r['stderr'],
                })
    except Exception as e:
        error = str(e)
    return render(request, 'clusters/cluster_test.html', {
        'cluster': cluster,
        'results': results,
        'error': error,
    })


# ─── Nodes ───────────────────────────────────────────────────────────────────

@login_required
def node_list(request, cluster_pk):
    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    nodes = cluster.nodes.all()
    return render(request, 'dashboard/node_list.html', {'cluster': cluster, 'nodes': nodes})


@login_required
def node_detail(request, cluster_pk, node_ip):
    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    node = get_object_or_404(Node, cluster=cluster, ip_address=node_ip)
    operations = node.operations.order_by('-started_at')[:20]
    restart_form = RestartServiceForm()
    return render(request, 'dashboard/node_detail.html', {
        'cluster': cluster,
        'node': node,
        'operations': operations,
        'restart_form': restart_form,
    })


@login_required
def cluster_node_config(request, cluster_pk):
    """AJAX: fetch existing machine config from a node of given role."""
    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    role = request.GET.get('role', 'worker')
    node = cluster.nodes.filter(role=role).first()
    if not node:
        node = cluster.nodes.first()
    if not node:
        return JsonResponse({'success': False, 'error': 'No nodes found in this cluster.'})
    try:
        with TalosctlRunner(cluster) as t:
            result = t.get_machineconfig(node.ip_address)
        if result['success'] and result['stdout'].strip():
            return JsonResponse({'success': True, 'config': result['stdout'], 'node': node.ip_address})
        else:
            err = result['stderr'] or result['stdout'] or 'Empty response from node.'
            return JsonResponse({'success': False, 'error': err})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def node_add(request, cluster_pk):
    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    if not request.user.profile.is_operator:
        messages.error(request, 'Insufficient permissions.')
        return redirect('clusters:detail', pk=cluster_pk)

    node_form = NodeForm(request.POST or None)
    config_form = NodeApplyConfigForm(request.POST or None)

    if request.method == 'POST':
        apply_config = request.POST.get('apply_config') == '1'

        node_valid = node_form.is_valid()
        config_valid = (not apply_config) or config_form.is_valid()

        if node_valid and config_valid:
            node = node_form.save(commit=False)
            node.cluster = cluster
            node.save()

            if apply_config:
                config_content = config_form.cleaned_data['config_content']
                insecure = config_form.cleaned_data.get('insecure', True)
                import tempfile, os as _os
                tmp = None
                try:
                    tmp = tempfile.NamedTemporaryFile(
                        mode='w', suffix='.yaml', delete=False, dir='/tmp', encoding='utf-8'
                    )
                    tmp.write(config_content)
                    tmp.close()
                    _os.chmod(tmp.name, 0o600)
                    with TalosctlRunner(cluster) as t:
                        result = t.apply_config(node.ip_address, tmp.name, insecure=insecure)
                    if result['success']:
                        node.status = 'provisioning'
                        node.save(update_fields=['status'])
                        messages.success(request, f'Node {node.ip_address} added and config applied.')
                    else:
                        err = result['stderr'] or result['stdout'] or 'Unknown error'
                        messages.warning(request, f'Node saved but config apply failed: {err}')
                except Exception as e:
                    messages.warning(request, f'Node saved but config apply error: {e}')
                finally:
                    if tmp is not None and _os.path.exists(tmp.name):
                        _os.unlink(tmp.name)
            else:
                messages.success(request, f'Node {node.ip_address} added to cluster.')

            return redirect('clusters:node_detail', cluster_pk=cluster_pk, node_ip=node.ip_address)

    return render(request, 'clusters/node_form.html', {
        'node_form': node_form,
        'config_form': config_form,
        'cluster': cluster,
    })


# ─── Node Operations ─────────────────────────────────────────────────────────

def _run_node_op(request, cluster_pk, node_ip, operation, extra_args=None):
    """Common logic for node operations."""
    if not request.user.profile.is_operator:
        return JsonResponse({'error': 'Insufficient permissions'}, status=403)

    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    node = get_object_or_404(Node, cluster=cluster, ip_address=node_ip)

    op = NodeOperation.objects.create(
        node=node,
        operation=operation,
        status=NodeOperation.STATUS_RUNNING,
        initiated_by=request.user,
    )

    try:
        with TalosctlRunner(cluster) as t:
            if operation == NodeOperation.OP_REBOOT:
                result = t.reboot(node_ip)
            elif operation == NodeOperation.OP_SHUTDOWN:
                result = t.shutdown(node_ip)
            elif operation == NodeOperation.OP_RESET:
                result = t.reset(node_ip)
            elif operation == NodeOperation.OP_RESTART_SERVICE:
                service = (extra_args or {}).get('service', '')
                op.service_name = service
                result = t.restart_service(node_ip, service)
            else:
                result = {'success': False, 'stderr': 'Unknown operation'}

        op.status = NodeOperation.STATUS_SUCCESS if result['success'] else NodeOperation.STATUS_FAILED
        op.output = result.get('stdout', '') + result.get('stderr', '')
    except Exception as e:
        op.status = NodeOperation.STATUS_FAILED
        op.output = str(e)

    op.completed_at = timezone.now()
    op.save()

    return op


@login_required
@require_POST
def node_reboot(request, cluster_pk, node_ip):
    op = _run_node_op(request, cluster_pk, node_ip, NodeOperation.OP_REBOOT)
    if isinstance(op, JsonResponse):
        return op
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': op.status, 'output': op.output})
    messages.success(request, 'Reboot initiated.') if op.status == 'success' else messages.error(request, f'Reboot failed: {op.output}')
    return redirect('clusters:node_detail', cluster_pk=cluster_pk, node_ip=node_ip)


@login_required
@require_POST
def node_shutdown(request, cluster_pk, node_ip):
    op = _run_node_op(request, cluster_pk, node_ip, NodeOperation.OP_SHUTDOWN)
    if isinstance(op, JsonResponse):
        return op
    messages.success(request, 'Shutdown initiated.') if op.status == 'success' else messages.error(request, f'Shutdown failed: {op.output}')
    return redirect('clusters:node_detail', cluster_pk=cluster_pk, node_ip=node_ip)


@login_required
@require_POST
def node_reset(request, cluster_pk, node_ip):
    op = _run_node_op(request, cluster_pk, node_ip, NodeOperation.OP_RESET)
    if isinstance(op, JsonResponse):
        return op
    messages.success(request, 'Reset initiated.') if op.status == 'success' else messages.error(request, f'Reset failed: {op.output}')
    return redirect('clusters:node_detail', cluster_pk=cluster_pk, node_ip=node_ip)


@login_required
@require_POST
def node_restart_service(request, cluster_pk, node_ip):
    form = RestartServiceForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Invalid service name.')
        return redirect('clusters:node_detail', cluster_pk=cluster_pk, node_ip=node_ip)

    service = form.cleaned_data['service_name']
    op = _run_node_op(request, cluster_pk, node_ip, NodeOperation.OP_RESTART_SERVICE, {'service': service})
    if isinstance(op, JsonResponse):
        return op
    messages.success(request, f'Service {service} restarted.') if op.status == 'success' else messages.error(request, f'Restart failed: {op.output}')
    return redirect('clusters:node_detail', cluster_pk=cluster_pk, node_ip=node_ip)


# ─── Node Dashboard ───────────────────────────────────────────────────────────

@login_required
def node_dashboard(request, cluster_pk, node_ip):
    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    node = get_object_or_404(Node, cluster=cluster, ip_address=node_ip)
    return render(request, 'dashboard/node_dashboard.html', {
        'cluster': cluster,
        'node': node,
    })


@login_required
def node_dashboard_data(request, cluster_pk, node_ip):
    """HTMX partial: fetches live memory/processes/stats and returns HTML fragment."""
    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    node = get_object_or_404(Node, cluster=cluster, ip_address=node_ip)

    def run_cmd(name, args):
        try:
            with TalosctlRunner(cluster) as t:
                r = t.run(args, node_ip=node_ip, timeout=10)
                return name, r['stdout'] if r['success'] else ''
        except Exception:
            return name, ''

    cmds = [
        ('memory', ['memory']),
        ('stats', ['stats']),
        ('processes', ['processes']),
    ]

    raw = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(run_cmd, name, args): name for name, args in cmds}
        for future in as_completed(futures):
            name, output = future.result()
            raw[name] = output

    def normalize_keys(rows):
        """Replace characters invalid in Django template variable names."""
        return [
            {re.sub(r'[^A-Z0-9_]', '_', k): v for k, v in row.items()}
            for row in rows
        ]

    _, memory_rows = _parse_talosctl_table(raw.get('memory', ''))
    _, stats_rows = _parse_talosctl_table(raw.get('stats', ''))
    _, proc_rows = _parse_talosctl_table(raw.get('processes', ''))

    stats_rows = normalize_keys(stats_rows)
    proc_rows = normalize_keys(proc_rows)

    mem = memory_rows[0] if memory_rows else {}
    try:
        mem_pct = round(int(mem.get('USED', 0)) / int(mem.get('TOTAL', 1)) * 100)
    except (ValueError, ZeroDivisionError):
        mem_pct = 0

    return render(request, 'dashboard/node_dashboard_data.html', {
        'cluster': cluster,
        'node': node,
        'mem': mem,
        'mem_pct': mem_pct,
        'stats_rows': stats_rows,
        'proc_rows': proc_rows,
    })


# ─── MachineConfig Editor ────────────────────────────────────────────────────

@operator_required
@require_http_methods(["GET", "POST"])
def machineconfig_view(request, cluster_pk, node_ip):
    """GET: fetch current machineconfig and show editor. POST: apply edited config."""
    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    node = get_object_or_404(Node, cluster=cluster, ip_address=node_ip)

    if request.method == 'POST':
        form = MachineConfigForm(request.POST)
        if form.is_valid():
            try:
                with TalosctlRunner(cluster) as t:
                    result = t.apply_machineconfig(
                        node_ip,
                        form.cleaned_data['yaml_content'],
                        mode=form.cleaned_data['mode'],
                    )
                if result['success']:
                    messages.success(request, 'Machine configuration applied successfully.')
                    return redirect('clusters:node_detail', cluster_pk=cluster_pk, node_ip=node_ip)
                else:
                    error_msg = result['stderr'] or result['stdout'] or 'Unknown error'
                    messages.error(request, f'Failed to apply config: {error_msg}')
            except Exception as e:
                messages.error(request, f'Error applying config: {e}')
    else:
        # GET: fetch current config
        yaml_content = ''
        try:
            with TalosctlRunner(cluster) as t:
                result = t.get_machineconfig(node_ip)
                if result['success']:
                    yaml_content = result['stdout']
                else:
                    messages.warning(request, f'Could not fetch config: {result["stderr"]}')
        except Exception as e:
            messages.warning(request, f'Could not fetch config: {e}')
        form = MachineConfigForm(initial={'yaml_content': yaml_content, 'mode': 'auto'})

    return render(request, 'clusters/machineconfig_edit.html', {
        'cluster': cluster,
        'node': node,
        'form': form,
    })


@operator_required
@require_POST
def machineconfig_patch(request, cluster_pk, node_ip):
    """Apply a JSON patch to the node's machine configuration."""
    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    node = get_object_or_404(Node, cluster=cluster, ip_address=node_ip)

    patch_json = request.body.decode('utf-8')
    if not patch_json.strip():
        return JsonResponse({'error': 'Patch content cannot be empty.'}, status=400)

    try:
        import json as _json
        _json.loads(patch_json)
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON patch.'}, status=400)

    try:
        with TalosctlRunner(cluster) as t:
            result = t.patch_machineconfig(node_ip, patch_json)
        if result['success']:
            return JsonResponse({'success': True, 'output': result['stdout']})
        else:
            error_msg = result['stderr'] or result['stdout'] or 'Unknown error'
            return JsonResponse({'success': False, 'error': error_msg}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ─── Cluster Bootstrap Wizard ────────────────────────────────────────────────

@admin_required
@require_http_methods(["GET", "POST"])
def cluster_bootstrap(request):
    """
    3-step bootstrap wizard:
      Step 1: cluster info form
      Step 2: review/edit generated controlplane.yaml and worker.yaml
      Step 3: apply → create cluster in DB
    """
    step = request.POST.get('wizard_step', '1') if request.method == 'POST' else '1'

    # ── Step 1: validate form & generate configs ──────────────────────────────
    if request.method == 'POST' and step == '1':
        form = ClusterBootstrapForm(request.POST)
        if not form.is_valid():
            return render(request, 'clusters/cluster_bootstrap.html', {'form': form, 'wizard_step': 1})

        cluster_name = form.cleaned_data['cluster_name']
        endpoint = form.cleaned_data['endpoint']
        cp_nodes = form.cleaned_data['controlplane_nodes']   # [{ip, hostname}, ...]
        worker_nodes = form.cleaned_data['worker_nodes']

        output_dir = tempfile.mkdtemp(prefix='talos-bootstrap-')
        try:
            runner = TalosctlRunner.__new__(TalosctlRunner)
            runner.cluster = None
            runner._tmpfile_path = None
            result = runner.gen_config(cluster_name, endpoint, output_dir)

            if not result['success']:
                err = result['stderr'] or result['stdout'] or 'Unknown error'
                messages.error(request, f'Config generation failed: {err}')
                return render(request, 'clusters/cluster_bootstrap.html', {'form': form, 'wizard_step': 1})

            talosconfig_path = os.path.join(output_dir, 'talosconfig')
            cp_config_path = os.path.join(output_dir, 'controlplane.yaml')
            worker_config_path = os.path.join(output_dir, 'worker.yaml')

            if not os.path.exists(talosconfig_path):
                messages.error(request, 'talosconfig not generated.')
                return render(request, 'clusters/cluster_bootstrap.html', {'form': form, 'wizard_step': 1})

            with open(talosconfig_path) as f:
                talosconfig_content = f.read()
            with open(cp_config_path) as f:
                cp_yaml = f.read()
            worker_yaml = ''
            if os.path.exists(worker_config_path):
                with open(worker_config_path) as f:
                    worker_yaml = f.read()
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

        cp_net_config = form.cleaned_data.get('cp_net_config', {'enabled': False})
        worker_net_config = form.cleaned_data.get('worker_net_config', {'enabled': False})

        # Store everything in session for step 2
        request.session['bootstrap'] = {
            'cluster_name': cluster_name,
            'endpoint': endpoint,
            'cp_nodes': cp_nodes,
            'worker_nodes': worker_nodes,
            'talosconfig': talosconfig_content,
            'cp_yaml': cp_yaml,
            'worker_yaml': worker_yaml,
            'cp_net_config': cp_net_config,
            'worker_net_config': worker_net_config,
        }

        return render(request, 'clusters/cluster_bootstrap.html', {
            'wizard_step': 2,
            'cluster_name': cluster_name,
            'endpoint': endpoint,
            'cp_nodes': cp_nodes,
            'worker_nodes': worker_nodes,
            'cp_yaml': cp_yaml,
            'worker_yaml': worker_yaml,
        })

    # ── Step 2: apply edited configs ─────────────────────────────────────────
    if request.method == 'POST' and step == '2':
        data = request.session.get('bootstrap')
        if not data:
            messages.error(request, 'Session expired. Please start over.')
            return redirect('clusters:bootstrap')

        cp_yaml = request.POST.get('cp_yaml', data['cp_yaml'])
        worker_yaml = request.POST.get('worker_yaml', data['worker_yaml'])
        cp_nodes = data['cp_nodes']       # [{ip, hostname}, ...]
        worker_nodes = data['worker_nodes']
        endpoint = data['endpoint']
        cluster_name = data['cluster_name']
        talosconfig_content = data['talosconfig']
        cp_net_config = data.get('cp_net_config', {'enabled': False})
        worker_net_config = data.get('worker_net_config', {'enabled': False})

        endpoint_clean = endpoint.replace('https://', '').replace('http://', '').rstrip('/')
        cluster = Cluster.objects.create(
            name=cluster_name,
            endpoint=endpoint_clean,
            talosconfig_content=talosconfig_content,
            created_by=request.user,
        )

        apply_errors = []

        def _build_network_patch(node_ip, net_config):
            """Build a machine.network dict from net_config and the node's IP."""
            if not net_config or not net_config.get('enabled'):
                return None
            prefix = net_config.get('prefix', 24)
            address = f"{node_ip}/{prefix}"
            gateway = net_config.get('gateway', '')
            nameservers = [s.strip() for s in net_config.get('nameservers', []) if s.strip()]

            iface_entry = {}
            if net_config.get('type') == 'bond':
                bond_name = net_config.get('bond_name', 'bond0')
                members = [m.strip() for m in net_config.get('bond_members', []) if m.strip()]
                bond_mode = net_config.get('bond_mode', '802.3ad')
                bond_def = {
                    'mode': bond_mode,
                    'miimon': int(net_config.get('miimon', 100)),
                    'interfaces': members,
                }
                if bond_mode == '802.3ad':
                    bond_def['lacpRate'] = net_config.get('lacp_rate', 'fast')
                iface_entry['interface'] = bond_name
                iface_entry['bond'] = bond_def
            else:
                iface_entry['interface'] = net_config.get('interface', 'eth0')

            iface_entry['dhcp'] = False
            iface_entry['addresses'] = [address]
            if gateway:
                iface_entry['routes'] = [{'network': '0.0.0.0/0', 'gateway': gateway}]

            vlans_raw = net_config.get('vlans', [])
            vlans = []
            for v in vlans_raw:
                vlan_entry = {'vlanId': int(v['id']), 'dhcp': bool(v.get('dhcp', False))}
                if not vlan_entry['dhcp'] and v.get('address', '').strip():
                    vlan_entry['addresses'] = [v['address'].strip()]
                vlans.append(vlan_entry)
            if vlans:
                iface_entry['vlans'] = vlans

            patch = {'interfaces': [iface_entry]}
            if nameservers:
                patch['nameservers'] = nameservers
            return patch

        def _patch_node_config(yaml_content, hostname, node_ip, net_config):
            """Inject hostname and/or network config into machine config YAML."""
            if not hostname and not (net_config and net_config.get('enabled')):
                return yaml_content
            try:
                import yaml as _yaml
                cfg = _yaml.safe_load(yaml_content)
                machine = cfg.setdefault('machine', {})
                network = machine.setdefault('network', {})
                if hostname:
                    network['hostname'] = hostname
                if net_config and net_config.get('enabled'):
                    net_patch = _build_network_patch(node_ip, net_config)
                    if net_patch:
                        if 'nameservers' in net_patch:
                            network['nameservers'] = net_patch['nameservers']
                        existing_ifaces = network.get('interfaces', [])
                        # Replace any existing interfaces list with patched one
                        network['interfaces'] = net_patch['interfaces'] + [
                            i for i in existing_ifaces
                            if i.get('interface') not in
                            [pi.get('interface') for pi in net_patch['interfaces']]
                        ]
                return _yaml.dump(cfg, default_flow_style=False, allow_unicode=True)
            except Exception:
                return yaml_content  # fall back to original if YAML manipulation fails

        def _apply(node_info, base_yaml, role, role_net_config=None):
            ip = node_info['ip']
            hostname = node_info.get('hostname', '')
            # Per-node override takes priority over role-level default
            net_config = node_info.get('net_config') or role_net_config
            yaml_content = _patch_node_config(base_yaml, hostname, ip, net_config)
            tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.yaml', delete=False, dir='/tmp', encoding='utf-8'
            )
            tmp.write(yaml_content)
            tmp.close()
            os.chmod(tmp.name, 0o600)
            try:
                with TalosctlRunner(cluster) as t:
                    r = t.apply_config(ip, tmp.name, insecure=True)
                if r['success']:
                    Node.objects.create(
                        cluster=cluster,
                        ip_address=ip,
                        hostname=hostname,
                        role=role,
                        status='provisioning',
                    )
                else:
                    apply_errors.append(f'{ip}: {r["stderr"] or r["stdout"]}')
            finally:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)

        for node_info in cp_nodes:
            _apply(node_info, cp_yaml, Node.ROLE_CONTROLPLANE, role_net_config=cp_net_config)

        if worker_yaml:
            for node_info in worker_nodes:
                _apply(node_info, worker_yaml, Node.ROLE_WORKER, role_net_config=worker_net_config)

        # Bootstrap etcd on the first control plane node
        bootstrap_error = None
        if cp_nodes and not apply_errors:
            try:
                import time as _time
                # Wait for the node to finish initial setup before bootstrapping
                _time.sleep(10)
                with TalosctlRunner(cluster) as t:
                    r = t.bootstrap(cp_nodes[0]['ip'])
                if not r['success']:
                    bootstrap_error = r['stderr'] or r['stdout'] or 'Unknown error'
            except Exception as e:
                bootstrap_error = str(e)

        del request.session['bootstrap']

        if apply_errors:
            messages.warning(request, 'Cluster created with errors: ' + '; '.join(apply_errors))
        elif bootstrap_error:
            messages.warning(request, f'Configs applied but bootstrap failed: {bootstrap_error}')
        else:
            messages.success(request, f'Cluster "{cluster_name}" bootstrapped successfully.')

        return redirect('clusters:detail', pk=cluster.pk)

    # ── Step 1 GET ────────────────────────────────────────────────────────────
    form = ClusterBootstrapForm()
    return render(request, 'clusters/cluster_bootstrap.html', {'form': form, 'wizard_step': 1})


# ─── Node Apply Config ───────────────────────────────────────────────────────

@operator_required
@require_http_methods(["GET", "POST"])
def node_apply_config(request, cluster_pk, node_ip):
    """Apply a configuration file to an existing node."""
    cluster = get_object_or_404(Cluster, pk=cluster_pk)
    node = get_object_or_404(Node, cluster=cluster, ip_address=node_ip)

    if request.method == 'POST':
        form = NodeApplyConfigForm(request.POST)
        if form.is_valid():
            config_content = form.cleaned_data['config_content']
            insecure = form.cleaned_data['insecure']

            # Write config to temp file
            tmp = None
            try:
                tmp = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.yaml', delete=False, dir='/tmp', encoding='utf-8'
                )
                tmp.write(config_content)
                tmp.close()
                os.chmod(tmp.name, 0o600)

                with TalosctlRunner(cluster) as t:
                    result = t.apply_config(node_ip, tmp.name, insecure=insecure)

                if result['success']:
                    node.status = 'provisioning'
                    node.save(update_fields=['status'])
                    messages.success(request, f'Configuration applied to {node_ip}.')
                    return redirect('clusters:node_detail', cluster_pk=cluster_pk, node_ip=node_ip)
                else:
                    error_msg = result['stderr'] or result['stdout'] or 'Unknown error'
                    messages.error(request, f'Failed to apply config: {error_msg}')
            except Exception as e:
                messages.error(request, f'Error applying config: {e}')
            finally:
                if tmp is not None and os.path.exists(tmp.name):
                    os.unlink(tmp.name)
    else:
        form = NodeApplyConfigForm()

    return render(request, 'clusters/node_apply_config.html', {
        'cluster': cluster,
        'node': node,
        'form': form,
    })
