{{/*
Chart name truncated to 63 chars.
*/}}
{{- define "fraud-guard.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. Uses release name + chart name, truncated to 63 chars.
*/}}
{{- define "fraud-guard.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "fraud-guard.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{/*
Selector labels for a specific component.
Usage: include "fraud-guard.selectorLabels" (dict "context" . "component" "fastapi")
*/}}
{{- define "fraud-guard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "fraud-guard.name" .context }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Service name helpers for inter-service DNS.
*/}}
{{- define "fraud-guard.postgresService" -}}
{{ include "fraud-guard.fullname" . }}-postgres
{{- end }}

{{- define "fraud-guard.kafkaService" -}}
{{ include "fraud-guard.fullname" . }}-kafka
{{- end }}

{{- define "fraud-guard.fastapiService" -}}
{{ include "fraud-guard.fullname" . }}-fastapi
{{- end }}

{{- define "fraud-guard.sparkMasterService" -}}
{{ include "fraud-guard.fullname" . }}-spark-master
{{- end }}

{{- define "fraud-guard.prometheusService" -}}
{{ include "fraud-guard.fullname" . }}-prometheus
{{- end }}

{{- define "fraud-guard.grafanaService" -}}
{{ include "fraud-guard.fullname" . }}-grafana
{{- end }}
