import subprocess
import tempfile
import os
import json


class TalosctlRunner:
    """
    Context manager that writes the cluster talosconfig to a temp file
    and provides methods to run talosctl commands securely.

    Usage:
        with TalosctlRunner(cluster) as t:
            result = t.run(['get', 'members', '-o', 'json'])
            for line in t.run_stream(['logs', 'kubelet', '--follow'], node_ip='10.0.0.1'):
                print(line)
    """

    def __init__(self, cluster):
        self.cluster = cluster
        self._tmpfile_path = None

    def __enter__(self):
        # Normalize line endings (Windows \r\n → \n) and strip trailing whitespace
        content = self.cluster.talosconfig_content
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False, dir='/tmp', encoding='utf-8'
        )
        tmp.write(content)
        tmp.close()
        os.chmod(tmp.name, 0o600)
        self._tmpfile_path = tmp.name
        return self

    def __exit__(self, *args):
        if self._tmpfile_path and os.path.exists(self._tmpfile_path):
            os.unlink(self._tmpfile_path)
            self._tmpfile_path = None

    def _base_cmd(self, node_ip=None):
        """Build base talosctl command.

        node_ip can be:
          - None        → use endpoint IP as single node
          - str         → single node IP
          - list[str]   → multiple nodes (adds -n for each)
        """
        cmd = ['talosctl', '--talosconfig', self._tmpfile_path]
        endpoint = getattr(self.cluster, 'endpoint', '').strip()
        endpoint = endpoint.replace('https://', '').replace('http://', '')
        # Strip port — talosctl uses Talos API port (50000) by default.
        # The stored endpoint may include the Kubernetes API port (6443).
        endpoint_host = endpoint.split(':')[0]
        if endpoint_host:
            cmd += ['--endpoints', endpoint_host]

        if isinstance(node_ip, list):
            for ip in node_ip:
                cmd += ['-n', ip]
        else:
            target = node_ip or endpoint.split(':')[0]
            if target:
                cmd += ['-n', target]
        return cmd

    def run(self, args: list, node_ip: str = None, timeout: int = 30) -> dict:
        """Run a talosctl command and return stdout/stderr/returncode."""
        cmd = self._base_cmd(node_ip) + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
                'success': result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {
                'stdout': '',
                'stderr': f'Command timed out after {timeout}s',
                'returncode': -1,
                'success': False,
            }
        except FileNotFoundError:
            return {
                'stdout': '',
                'stderr': 'talosctl not found. Please install talosctl.',
                'returncode': -1,
                'success': False,
            }

    def run_json(self, args: list, node_ip: str = None, timeout: int = 30):
        """Run a talosctl command expecting JSON output. Returns parsed dict or None."""
        result = self.run(args + ['-o', 'json'], node_ip=node_ip, timeout=timeout)
        if result['success']:
            try:
                return json.loads(result['stdout'])
            except json.JSONDecodeError:
                return None
        return None

    def run_stream(self, args: list, node_ip: str = None):
        """Generator: yields output lines one by one (for WebSocket streaming)."""
        cmd = self._base_cmd(node_ip) + args
        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            ) as proc:
                for line in proc.stdout:
                    yield line.rstrip()
        except FileNotFoundError:
            yield 'ERROR: talosctl not found. Please install talosctl.'

    def get_members(self):
        """Return (members_list, error_str).

        Handles both JSONL (one object per line) and pretty-printed multi-line JSON
        output from talosctl get members -o json.
        """
        result = self.run(['get', 'members', '-o', 'json'])
        if not result['success']:
            err = (result['stderr'] or result['stdout'] or 'unknown error').strip()
            return [], err

        # Use raw_decode to consume multiple JSON objects from the full stdout,
        # regardless of whether they are on one line or pretty-printed.
        decoder = json.JSONDecoder()
        text = result['stdout'].strip()
        objects = []
        idx = 0
        while idx < len(text):
            # Skip whitespace between objects
            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text):
                break
            try:
                obj, end_idx = decoder.raw_decode(text, idx)
                objects.append(obj)
                idx = end_idx
            except json.JSONDecodeError:
                break

        members = []
        for obj in objects:
            if not isinstance(obj, dict):
                continue

            spec = obj.get('spec', {})

            # Talos v1.11+: addresses is a list e.g. ["10.1.57.11"]
            # Older versions: address is a string e.g. "10.1.57.10/32"
            addresses = spec.get('addresses')
            if addresses and isinstance(addresses, list):
                ip = addresses[0].split('/')[0].strip()
            else:
                ip = spec.get('address', '').split('/')[0].strip()
            if not ip:
                continue

            machine_type = spec.get('machineType', spec.get('machine_type', 'worker')).lower()
            role = 'controlplane' if 'control' in machine_type else 'worker'

            # Talos v1.11+: talosVersion not in member spec; parse from operatingSystem
            talos_ver = spec.get('talosVersion', spec.get('talos_version', ''))
            if not talos_ver:
                import re as _re
                m = _re.search(r'\(([^)]+)\)', spec.get('operatingSystem', ''))
                if m:
                    talos_ver = m.group(1)

            members.append({
                'ip': ip,
                'hostname': spec.get('hostname', ''),
                'role': role,
                'talos_version': talos_ver,
                'k8s_version': spec.get('kubeletVersion', spec.get('kubelet_version', '')),
            })

        return members, None

    def get_k8s_version(self, node_ip: str = None) -> str:
        """Return the Kubernetes version from kubeletspec image tag, e.g. 'v1.34.0'."""
        import re as _re
        result = self.run(['get', 'kubeletspec', '-o', 'json'], node_ip=node_ip, timeout=10)
        if not result['success']:
            return ''
        decoder = json.JSONDecoder()
        text = result['stdout'].strip()
        try:
            obj, _ = decoder.raw_decode(text, 0)
            image = obj.get('spec', {}).get('image', '')
            # e.g. "ghcr.io/siderolabs/kubelet:v1.34.0"
            m = _re.search(r':([v\d][^\s]+)$', image)
            if m:
                return m.group(1)
        except (json.JSONDecodeError, AttributeError):
            pass
        return ''

    def get_node_status(self, node_ip: str) -> dict:
        """Return node status information."""
        return self.run(['get', 'nodestatus', '-o', 'json'], node_ip=node_ip)

    def get_kubeconfig(self) -> dict:
        """Fetch admin kubeconfig and return its content as stdout."""
        import tempfile as _tmp, os as _os
        tmp = _tmp.NamedTemporaryFile(suffix='.yaml', delete=False, dir='/tmp')
        tmp.close()
        try:
            cmd = self._base_cmd() + ['kubeconfig', tmp.name, '--force']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and _os.path.exists(tmp.name):
                with open(tmp.name, 'r') as f:
                    content = f.read()
                return {'stdout': content, 'stderr': result.stderr, 'returncode': 0, 'success': True}
            return {'stdout': '', 'stderr': result.stderr or result.stdout, 'returncode': result.returncode, 'success': False}
        except subprocess.TimeoutExpired:
            return {'stdout': '', 'stderr': 'timed out', 'returncode': -1, 'success': False}
        except FileNotFoundError:
            return {'stdout': '', 'stderr': 'talosctl not found.', 'returncode': -1, 'success': False}
        finally:
            if _os.path.exists(tmp.name):
                _os.unlink(tmp.name)

    def bootstrap(self, node_ip: str) -> dict:
        """Bootstrap the etcd cluster on the given control plane node.

        Uses the node's own IP as the endpoint so talosctl connects to the
        Talos API port (50000) directly, not the Kubernetes API port (6443).
        """
        cmd = ['talosctl', '--talosconfig', self._tmpfile_path,
               '--endpoints', node_ip, '-n', node_ip, 'bootstrap']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
                'success': result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {'stdout': '', 'stderr': 'bootstrap timed out after 120s', 'returncode': -1, 'success': False}
        except FileNotFoundError:
            return {'stdout': '', 'stderr': 'talosctl not found.', 'returncode': -1, 'success': False}

    def reboot(self, node_ip: str) -> dict:
        return self.run(['reboot'], node_ip=node_ip, timeout=60)

    def shutdown(self, node_ip: str) -> dict:
        return self.run(['shutdown'], node_ip=node_ip, timeout=60)

    def reset(self, node_ip: str, graceful: bool = True) -> dict:
        args = ['reset']
        if graceful:
            args.append('--graceful')
        return self.run(args, node_ip=node_ip, timeout=120)

    def restart_service(self, node_ip: str, service: str) -> dict:
        return self.run(['service', service, 'restart'], node_ip=node_ip)

    def upgrade(self, node_ip: str, image_url: str) -> dict:
        return self.run(
            ['upgrade', '--image', image_url, '--wait'],
            node_ip=node_ip,
            timeout=600,
        )

    def upgrade_stream(self, node_ip: str, image_url: str):
        """Generator: yields (line, is_done, success) tuples for image upgrade."""
        args = ['upgrade', '--image', image_url, '--wait']
        cmd = self._base_cmd(node_ip) + args
        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            ) as proc:
                for line in proc.stdout:
                    yield line.rstrip(), False, None
                proc.wait()
                yield '', True, proc.returncode == 0
        except FileNotFoundError:
            yield 'ERROR: talosctl not found.', True, False

    def upgrade_k8s(self, to_version: str) -> dict:
        return self.run(['upgrade-k8s', '--to', to_version], timeout=600)

    def upgrade_k8s_stream(self, to_version: str):
        """Generator: yields (line, is_done, success) tuples for k8s upgrade."""
        args = ['upgrade-k8s', '--to', to_version]
        cmd = self._base_cmd() + args
        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            ) as proc:
                for line in proc.stdout:
                    yield line.rstrip(), False, None
                proc.wait()
                yield '', True, proc.returncode == 0
        except FileNotFoundError:
            yield 'ERROR: talosctl not found.', True, False

    def get_machineconfig(self, node_ip: str) -> dict:
        """Fetch the current machine configuration as YAML (spec content only).

        talosctl get mc -o yaml wraps the config in a resource envelope.
        We extract the raw text under 'spec:' to preserve original formatting.
        """
        result = self.run(['get', 'mc', '-o', 'yaml'], node_ip=node_ip, timeout=30)
        if not result['success']:
            return result
        try:
            import yaml as _yaml
            docs = list(_yaml.safe_load_all(result['stdout']))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                spec = doc.get('spec')
                if spec is None:
                    continue
                if isinstance(spec, str):
                    # Talos v1.11+: spec is a quoted string with \r\n line endings
                    extracted = spec.replace('\r\n', '\n').replace('\r', '\n').strip()
                elif isinstance(spec, dict):
                    extracted = _yaml.dump(spec, default_flow_style=False, allow_unicode=True).strip()
                else:
                    continue
                if extracted:
                    result['stdout'] = extracted
                    break
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning('get_machineconfig YAML parse failed: %s', e)
            # Fall back to raw output
        return result

    def apply_machineconfig(self, node_ip: str, config_yaml: str, mode: str = 'auto') -> dict:
        """Apply a machine configuration from YAML string.

        mode: auto | interactive | reboot | no-reboot | staged
        """
        valid_modes = ('auto', 'interactive', 'reboot', 'no-reboot', 'staged')
        if mode not in valid_modes:
            return {
                'stdout': '',
                'stderr': f'Invalid mode "{mode}". Must be one of: {", ".join(valid_modes)}',
                'returncode': -1,
                'success': False,
            }
        # Write config to a temp file to avoid shell injection
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False, dir='/tmp', encoding='utf-8'
        )
        tmp.write(config_yaml)
        tmp.close()
        os.chmod(tmp.name, 0o600)
        try:
            args = ['apply-config', '-f', tmp.name, '--mode', mode]
            return self.run(args, node_ip=node_ip, timeout=120)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def patch_machineconfig(self, node_ip: str, patch_content: str) -> dict:
        """Apply a JSON or YAML patch to the machine configuration.

        patch_content: JSON patch array (RFC 6902) or YAML merge patch string.
        """
        # Always use .yaml suffix — talosctl patch machineconfig treats
        # JSON arrays as merge patches (not RFC 6902) regardless of extension,
        # and .yaml works for both JSON and YAML content.
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False, dir='/tmp', encoding='utf-8'
        )
        tmp.write(patch_content)
        tmp.close()
        os.chmod(tmp.name, 0o600)
        try:
            args = ['patch', 'machineconfig', '--patch', f'@{tmp.name}']
            return self.run(args, node_ip=node_ip, timeout=60)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def gen_config(self, cluster_name: str, endpoint: str, output_dir: str) -> dict:
        """Generate initial Talos config files.

        Creates controlplane.yaml, worker.yaml, and talosconfig in output_dir.
        Does not require an existing talosconfig or cluster connection.
        """
        cmd = ['talosctl', 'gen', 'config', cluster_name, endpoint,
               '--output-dir', output_dir]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
                'success': result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {
                'stdout': '',
                'stderr': 'gen config timed out after 30s',
                'returncode': -1,
                'success': False,
            }
        except FileNotFoundError:
            return {
                'stdout': '',
                'stderr': 'talosctl not found. Please install talosctl.',
                'returncode': -1,
                'success': False,
            }

    def apply_config(self, node_ip: str, config_path: str, insecure: bool = False) -> dict:
        """Apply a config file to a node.

        insecure: use --insecure flag (for initial node setup before PKI is established).
        """
        args = ['apply-config', '--file', config_path]
        if insecure:
            args.append('--insecure')
        return self.run(args, node_ip=node_ip, timeout=120)
