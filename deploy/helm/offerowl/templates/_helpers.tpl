{{/*
Names and labels. Every object is called "<fullname>" (with a suffix where one release needs two of a kind): a release
called "offerowl" has a Deployment, a Service and a claim named offerowl, offerowl and offerowl-data.
*/}}

{{- define "offerowl.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "offerowl.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* The labels the pods are selected by. They never change after the first install: a Deployment's selector is fixed. */}}
{{- define "offerowl.selectorLabels" -}}
app.kubernetes.io/name: {{ include "offerowl.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Every label of the chart's objects. */}}
{{- define "offerowl.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "offerowl.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* "repository:tag", the tag defaulting to the chart's appVersion. */}}
{{- define "offerowl.image" -}}
{{- printf "%s:%s" .Values.image.repository (toString (.Values.image.tag | default .Chart.AppVersion)) -}}
{{- end -}}

{{/* The claim the data folder lives on: the one you name, or the one the chart makes. */}}
{{- define "offerowl.claimName" -}}
{{- .Values.persistence.existingClaim | default (printf "%s-data" (include "offerowl.fullname" .)) -}}
{{- end -}}

{{/* storageClassName for a persistence block: left out when empty (the default class), "" for "-". */}}
{{- define "offerowl.storageClass" -}}
{{- if .storageClass -}}
{{- if eq "-" (toString .storageClass) -}}
storageClassName: ""
{{- else -}}
storageClassName: {{ .storageClass | quote }}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
The Host header the panel accepts: this PC's loopback and its own port. A probe or a test pod that asks the pod's address
would be refused as a foreign host, so they send this one.
*/}}
{{- define "offerowl.hostHeader" -}}
{{- printf "127.0.0.1:%d" (int .Values.service.panelPort) -}}
{{- end -}}

{{/*
Settings that cannot work, refused before anything is rendered, with the sentence that says what to change.
*/}}
{{- define "offerowl.validate" -}}
{{- $backend := toString .Values.ai.backend -}}
{{- if not (has $backend (list "none" "openai-compat")) -}}
{{- fail (printf "ai.backend must be none or openai-compat, not %q. Claude Code and Codex are not in the image: stay signed in to them on your own PC, or use a local model server." $backend) -}}
{{- end -}}
{{- if and (eq $backend "openai-compat") (not .Values.ai.url) -}}
{{- fail "ai.backend=openai-compat needs ai.url, the address of the model server (for example http://ollama.models.svc:11434)" -}}
{{- end -}}
{{- if and .Values.ai.existingSecret (not .Values.ai.secretKey) -}}
{{- fail "ai.existingSecret needs ai.secretKey, the name of the key inside that Secret" -}}
{{- end -}}
{{- $panel := int .Values.service.panelPort -}}
{{- if or (lt $panel 1024) (gt $panel 65535) -}}
{{- fail "service.panelPort must be between 1024 and 65535: the pod does not run as root, so it cannot listen on a lower port" -}}
{{- end -}}
{{- if and .Values.ingress.enabled (not .Values.ingress.hosts) -}}
{{- fail "ingress.enabled needs at least one entry in ingress.hosts" -}}
{{- end -}}
{{- $reserved := list "OFFEROWL_PANEL_PORT" "OFFEROWL_DATA_DIR" "OFFEROWL_LLM" "OFFEROWL_LLM_URL" "OFFEROWL_LLM_MODEL" "OFFEROWL_LLM_KEY" "OFFEROWL_ALLOWED_HOSTS" "OFFEROWL_DESKTOP" "OFFEROWL_LANG" "HOME" "TZ" -}}
{{- range $var := .Values.extraEnv -}}
{{- if has (toString $var.name) $reserved -}}
{{- fail (printf "extraEnv may not set %s: the chart or the image sets it (values.yaml, extraEnv)" $var.name) -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* The Ingress' host names as one comma-separated list, the form of OFFEROWL_ALLOWED_HOSTS. */}}
{{- define "offerowl.ingressHosts" -}}
{{- $hosts := list -}}
{{- range .Values.ingress.hosts -}}
{{- $hosts = append $hosts .host -}}
{{- end -}}
{{- join "," $hosts -}}
{{- end -}}
