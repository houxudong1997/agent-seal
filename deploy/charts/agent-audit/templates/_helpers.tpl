{{/*
Expand the name of the chart.
*/}}
{{- define "agent-audit.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "agent-audit.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "agent-audit.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "agent-audit.labels" -}}
helm.sh/chart: {{ include "agent-audit.chart" . }}
{{ include "agent-audit.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.global.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "agent-audit.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agent-audit.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "agent-audit.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "agent-audit.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Resolve DB URL: external > internal PostgreSQL.
Generates the full connection string including the real password.
Uses Helm's required() to fail fast with a clear error if password is not set.
*/}}
{{- define "agent-audit.dbUrl" -}}
{{- if not .Values.postgresql.enabled }}
{{- .Values.externalDb.url }}
{{- else }}
{{- $pw := required "postgresql.auth.password is required when postgresql.enabled=true" .Values.postgresql.auth.password -}}
{{- printf "postgresql://%s:%s@%s:%d/%s" .Values.postgresql.auth.username $pw (include "agent-audit.fullname" .) (int .Values.postgresql.service.port) .Values.postgresql.auth.database }}
{{- end }}
{{- end }}

{{/*
Resolve Redis URI: external > internal Redis
*/}}
{{- define "agent-audit.redisUri" -}}
{{- if not .Values.redis.enabled }}
{{- .Values.externalRedis.uri }}
{{- else }}
{{- printf "redis://%s-redis:%d/0" (include "agent-audit.fullname" .) (int .Values.redis.service.port) }}
{{- end }}
{{- end }}

{{/*
Docker image reference
*/}}
{{- define "agent-audit.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repo := .Values.image.repository -}}
{{- $tag := .Values.image.tag | toString -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end }}

{{/*
API keys as comma-separated string
*/}}
{{- define "agent-audit.apiKeysString" -}}
{{- join "," .Values.config.apiKeys }}
{{- end }}
