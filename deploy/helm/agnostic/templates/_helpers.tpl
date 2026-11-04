{{- define "agnostic.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agnostic.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "agnostic.labels" -}}
app.kubernetes.io/name: {{ include "agnostic.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "agnostic.selector" -}}
app.kubernetes.io/name: {{ include "agnostic.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "agnostic.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- if .Values.image.digest -}}
{{ .Values.image.repository }}@{{ .Values.image.digest }}
{{- else -}}
{{ .Values.image.repository }}:{{ $tag }}
{{- end -}}
{{- end -}}

{{- define "agnostic.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "agnostic.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Environment shared by every container: the ConfigMap, the existing Secret, extras. */}}
{{- define "agnostic.envFrom" -}}
- configMapRef:
    name: {{ include "agnostic.fullname" . }}
{{- if .Values.existingSecret }}
- secretRef:
    name: {{ .Values.existingSecret }}
{{- end }}
{{- with .Values.extraEnvFrom }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "agnostic.volumes" -}}
- name: tmp
  emptyDir:
    medium: Memory
    sizeLimit: 256Mi
- name: data
{{- if .Values.dataVolume.persistentVolumeClaim }}
  persistentVolumeClaim:
    claimName: {{ .Values.dataVolume.persistentVolumeClaim }}
{{- else }}
  emptyDir:
    sizeLimit: {{ .Values.dataVolume.sizeLimit }}
{{- end }}
{{- range .Values.extraSecretMounts }}
- name: {{ .name }}
  secret:
    secretName: {{ .secretName }}
{{- end }}
{{- end -}}

{{- define "agnostic.volumeMounts" -}}
- name: tmp
  mountPath: /tmp
- name: data
  mountPath: /var/lib/agnostic
{{- range .Values.extraSecretMounts }}
- name: {{ .name }}
  mountPath: {{ .mountPath }}
  readOnly: true
{{- end }}
{{- end -}}

{{/* Pod template pieces shared by the api and worker Deployments and the migrate Job. */}}
{{- define "agnostic.podSpecCommon" -}}
serviceAccountName: {{ include "agnostic.serviceAccountName" . }}
automountServiceAccountToken: {{ .Values.serviceAccount.create }}
securityContext:
  {{- toYaml .Values.podSecurityContext | nindent 2 }}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
volumes:
  {{- include "agnostic.volumes" . | nindent 2 }}
{{- end -}}

{{- define "agnostic.containerCommon" -}}
image: {{ include "agnostic.image" . }}
imagePullPolicy: {{ .Values.image.pullPolicy }}
securityContext:
  {{- toYaml .Values.securityContext | nindent 2 }}
envFrom:
  {{- include "agnostic.envFrom" . | nindent 2 }}
{{- with .Values.extraEnv }}
env:
  {{- toYaml . | nindent 2 }}
{{- end }}
volumeMounts:
  {{- include "agnostic.volumeMounts" . | nindent 2 }}
{{- end -}}

{{/* Non-secret settings: the ConfigMap's data, and inline env for the migrate hook (it runs before the ConfigMap). */}}
{{- define "agnostic.configMap" -}}
AGNOSTIC_HTTP__HOST: "0.0.0.0"
AGNOSTIC_HTTP__PORT: "8000"
AGNOSTIC_METRICS__ENABLED: {{ .Values.metrics.enabled | quote }}
AGNOSTIC_JOBS__CONCURRENCY: {{ .Values.worker.concurrency | quote }}
{{- with .Values.worker.queues }}
AGNOSTIC_JOBS__QUEUES: {{ join "," . | quote }}
{{- end }}
{{- range $key, $value := .Values.config }}
{{ $key }}: {{ $value | quote }}
{{- end }}
{{- end -}}

{{- define "agnostic.configEnv" -}}
{{- range $key, $value := (include "agnostic.configMap" . | fromYaml) }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}
