import re
from django import forms
from apps.clusters.models import Cluster, Node
from .models import UpgradeJob


class ImageUpgradeForm(forms.Form):
    cluster = forms.ModelChoiceField(queryset=Cluster.objects.filter(is_active=True))
    image_url = forms.CharField(
        max_length=500,
        help_text='e.g. ghcr.io/siderolabs/installer:v1.8.0',
        widget=forms.TextInput(attrs={'placeholder': 'ghcr.io/siderolabs/installer:v1.8.0'}),
    )
    target_nodes = forms.ModelMultipleChoiceField(
        queryset=Node.objects.none(),
        required=False,
        help_text='Leave empty to upgrade all nodes in the cluster.',
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'cluster' in self.data:
            try:
                cluster_id = int(self.data.get('cluster'))
                self.fields['target_nodes'].queryset = Node.objects.filter(cluster_id=cluster_id)
            except (ValueError, TypeError):
                pass
        elif self.initial.get('cluster'):
            self.fields['target_nodes'].queryset = Node.objects.filter(
                cluster=self.initial['cluster']
            )

    def clean_image_url(self):
        url = self.cleaned_data.get('image_url', '').strip()
        # Validate format: registry/image:tag
        if not re.match(r'^[\w.\-/]+:[\w.\-]+$', url):
            raise forms.ValidationError(
                'Invalid image URL format. Expected: registry/image:tag'
            )
        return url


class K8sUpgradeForm(forms.Form):
    cluster = forms.ModelChoiceField(queryset=Cluster.objects.filter(is_active=True))
    target_version = forms.CharField(
        max_length=20,
        help_text='e.g. 1.35.1 or 1.36.0',
        widget=forms.TextInput(attrs={'placeholder': '1.35.0'}),
    )

    def clean_target_version(self):
        version = self.cleaned_data.get('target_version', '').strip().lstrip('v')
        if not re.match(r'^\d+\.\d+\.\d+$', version):
            raise forms.ValidationError('Version must be in format X.Y.Z (e.g. 1.35.0)')
        return version

    def clean(self):
        cleaned_data = super().clean()
        cluster = cleaned_data.get('cluster')
        target_version = cleaned_data.get('target_version')
        if not cluster or not target_version:
            return cleaned_data

        current_version = (
            Node.objects.filter(cluster=cluster, k8s_version__gt='')
            .values_list('k8s_version', flat=True)
            .first()
        )
        if current_version:
            current_version = current_version.lstrip('v')
            try:
                cur_parts = tuple(int(x) for x in current_version.split('.'))
                tgt_parts = tuple(int(x) for x in target_version.split('.'))
                if tgt_parts <= cur_parts:
                    raise forms.ValidationError(
                        f'Target version {target_version} must be greater than '
                        f'current version {current_version}.'
                    )
            except (ValueError, IndexError):
                pass
        return cleaned_data
