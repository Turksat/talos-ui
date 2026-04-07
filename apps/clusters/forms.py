import ipaddress
import json
import re

import yaml
from django import forms
from .models import Cluster, Node


class ClusterForm(forms.ModelForm):
    class Meta:
        model = Cluster
        fields = ['name', 'endpoint', 'talosconfig_content']
        widgets = {
            'talosconfig_content': forms.Textarea(attrs={
                'rows': 20,
                'class': 'font-monospace',
                'placeholder': 'Paste your talosconfig YAML content here...',
            }),
            'endpoint': forms.TextInput(attrs={
                'placeholder': '192.168.1.10  or  192.168.1.10:50000',
            }),
        }

    def clean_endpoint(self):
        endpoint = self.cleaned_data.get('endpoint', '').strip()
        # Strip protocol if user pasted it
        endpoint = endpoint.replace('https://', '').replace('http://', '').rstrip('/')
        if not endpoint:
            raise forms.ValidationError('Endpoint cannot be empty.')
        return endpoint

    def clean_talosconfig_content(self):
        content = self.cleaned_data.get('talosconfig_content', '')
        # Normalize line endings
        content = content.replace('\r\n', '\n').replace('\r', '\n').strip()
        if not content:
            raise forms.ValidationError('Talosconfig content cannot be empty.')
        # Basic YAML sanity check
        if 'context' not in content and 'contexts' not in content:
            raise forms.ValidationError(
                'This does not appear to be a valid talosconfig (missing "context" key).'
            )
        # Validate it's parseable YAML
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise forms.ValidationError(f'Invalid YAML: {e}')
        return content


class NodeForm(forms.ModelForm):
    class Meta:
        model = Node
        fields = ['ip_address', 'hostname', 'role']


class RestartServiceForm(forms.Form):
    service_name = forms.CharField(
        max_length=100,
        help_text='e.g. kubelet, cri, etcd',
        widget=forms.TextInput(attrs={'placeholder': 'kubelet'}),
    )

    def clean_service_name(self):
        name = self.cleaned_data.get('service_name', '').strip()
        if not re.match(r'^[a-zA-Z0-9_\-]+$', name):
            raise forms.ValidationError(
                'Service name may only contain letters, digits, hyphens, and underscores.'
            )
        return name


class MachineConfigForm(forms.Form):
    MODE_CHOICES = [
        ('auto', 'Auto'),
        ('interactive', 'Interactive'),
        ('reboot', 'Reboot'),
        ('no-reboot', 'No Reboot'),
        ('staged', 'Staged'),
    ]

    yaml_content = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 30,
            'class': 'font-monospace',
            'placeholder': 'Machine configuration YAML...',
        }),
    )
    mode = forms.ChoiceField(
        choices=MODE_CHOICES,
        initial='auto',
        help_text='Config apply mode: auto detects if reboot is needed.',
    )

    def clean_yaml_content(self):
        content = self.cleaned_data.get('yaml_content', '')
        content = content.replace('\r\n', '\n').replace('\r', '\n').strip()
        if not content:
            raise forms.ValidationError('Configuration content cannot be empty.')
        try:
            list(yaml.safe_load_all(content))
        except yaml.YAMLError as e:
            raise forms.ValidationError(f'Invalid YAML: {e}')
        return content


class ClusterBootstrapForm(forms.Form):
    cluster_name = forms.CharField(
        max_length=200,
        help_text='Name for the new cluster.',
        widget=forms.TextInput(attrs={'placeholder': 'my-cluster'}),
    )
    endpoint = forms.CharField(
        max_length=500,
        help_text='Cluster endpoint URL (e.g. https://192.168.1.10:6443).',
        widget=forms.TextInput(attrs={'placeholder': 'https://192.168.1.10:6443'}),
    )
    # Encoded as "ip:hostname,ip:hostname" — hostname part is optional
    controlplane_nodes = forms.CharField(
        help_text='Control plane nodes as ip:hostname pairs.',
        widget=forms.HiddenInput(),
    )
    worker_nodes = forms.CharField(
        required=False,
        help_text='Worker nodes as ip:hostname pairs (optional).',
        widget=forms.HiddenInput(),
    )
    cp_net_config = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
        help_text='JSON-encoded network config for control plane nodes.',
    )
    worker_net_config = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
        help_text='JSON-encoded network config for worker nodes.',
    )

    def _parse_net_config(self, raw):
        """Parse and validate a JSON network config string, returning a dict."""
        if not raw or not raw.strip():
            return {'enabled': False}
        try:
            cfg = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise forms.ValidationError(f'Invalid JSON for network config: {exc}')
        if not isinstance(cfg, dict):
            raise forms.ValidationError('Network config must be a JSON object.')
        if not cfg.get('enabled', False):
            return {'enabled': False}
        # Basic structural validation when enabled
        if cfg.get('type') == 'bond':
            if not cfg.get('bond_name', '').strip():
                raise forms.ValidationError('Bond name is required when type is bond.')
            if not cfg.get('bond_members'):
                raise forms.ValidationError('At least one bond member NIC is required.')
        else:
            if not cfg.get('interface', '').strip():
                raise forms.ValidationError('Interface name is required for Physical NIC type.')
        prefix = cfg.get('prefix')
        if prefix is not None:
            try:
                prefix = int(prefix)
                if not (0 <= prefix <= 32):
                    raise forms.ValidationError('Subnet prefix must be between 0 and 32.')
                cfg['prefix'] = prefix
            except (TypeError, ValueError):
                raise forms.ValidationError('Subnet prefix must be an integer.')
        return cfg

    def clean_cp_net_config(self):
        return self._parse_net_config(self.cleaned_data.get('cp_net_config', ''))

    def clean_worker_net_config(self):
        return self._parse_net_config(self.cleaned_data.get('worker_net_config', ''))

    def clean_endpoint(self):
        endpoint = self.cleaned_data.get('endpoint', '').strip()
        if not endpoint.startswith('https://') and not endpoint.startswith('http://'):
            endpoint = 'https://' + endpoint
        return endpoint

    def _parse_nodes(self, raw):
        """Parse JSON array [{ip, hostname, net_config?}, ...] into validated node list."""
        raw = raw.strip()
        if not raw:
            return []
        # JSON array format (new)
        if raw.startswith('['):
            try:
                items = json.loads(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                raise forms.ValidationError(f'Invalid node data JSON: {exc}')
            nodes = []
            for item in items:
                ip = item.get('ip', '').strip()
                if not ip:
                    continue
                try:
                    ipaddress.ip_address(ip)
                except ValueError:
                    raise forms.ValidationError(f'"{ip}" is not a valid IP address.')
                nodes.append({
                    'ip': ip,
                    'hostname': item.get('hostname', '').strip(),
                    'net_config': item.get('net_config') or None,
                })
            return nodes
        # Legacy comma-separated 'ip:hostname' format (backwards compat)
        nodes = []
        for part in raw.split(','):
            part = part.strip()
            if not part:
                continue
            if ':' in part:
                ip, hostname = part.split(':', 1)
                ip = ip.strip()
                hostname = hostname.strip()
            else:
                ip = part.strip()
                hostname = ''
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise forms.ValidationError(f'"{ip}" is not a valid IP address.')
            nodes.append({'ip': ip, 'hostname': hostname, 'net_config': None})
        return nodes

    def clean_controlplane_nodes(self):
        raw = self.cleaned_data.get('controlplane_nodes', '')
        nodes = self._parse_nodes(raw)
        if not nodes:
            raise forms.ValidationError('At least one control plane node IP is required.')
        return nodes

    def clean_worker_nodes(self):
        raw = self.cleaned_data.get('worker_nodes', '')
        if not raw.strip():
            return []
        return self._parse_nodes(raw)


class NodeApplyConfigForm(forms.Form):
    CONFIG_TYPE_CHOICES = [
        ('custom', 'Upload/paste custom config'),
    ]

    config_content = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 20,
            'class': 'font-monospace',
            'placeholder': 'Paste node configuration YAML here...',
        }),
        help_text='YAML configuration to apply to the node.',
    )
    insecure = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Use --insecure flag (required for initial node setup before PKI is established).',
    )

    def clean_config_content(self):
        content = self.cleaned_data.get('config_content', '')
        content = content.replace('\r\n', '\n').replace('\r', '\n').strip()
        if not content:
            raise forms.ValidationError('Configuration content cannot be empty.')
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise forms.ValidationError(f'Invalid YAML: {e}')
        return content
