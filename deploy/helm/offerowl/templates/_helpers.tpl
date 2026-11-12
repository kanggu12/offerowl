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

{{/*
The objects of one Offerowl: "<fullname>" for the release's own (tenants empty), "<fullname>-<person>" for each person in
tenants. The context is the one "offerowl.instances" makes: .Values (the release's values with the person's on top),
.Release, .Chart and .Tenant (the person's name, empty for the release's own).
*/}}
{{- define "offerowl.instanceName" -}}
{{- if .Tenant -}}
{{- printf "%s-%s" (include "offerowl.fullname" .) .Tenant -}}
{{- else -}}
{{- include "offerowl.fullname" . -}}
{{- end -}}
{{- end -}}

{{/*
The labels the pods are selected by. They never change after the first install: a Deployment's selector is fixed. A
person's Offerowl adds their name, so the pods of one release's people are told apart; the release's own keeps the two
labels it always had.
*/}}
{{- define "offerowl.selectorLabels" -}}
app.kubernetes.io/name: {{ include "offerowl.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- with .Tenant }}
offerowl/tenant: {{ . }}
{{- end }}
{{- end -}}

{{/*
The Offerowls this release runs, put into .holder.instances: the release's own when tenants is empty, else one per person,
each a context for the templates (see "offerowl.instanceName"). A person's values are the release's with their own
fields on top: ai, resources, persistence, language, timezone, podAnnotations, nodeSelector, tolerations and affinity
merge or replace; extraEnv adds to the release's; ingress gives their host name, annotations and TLS.
*/}}
{{- define "offerowl.instances" -}}
{{- $root := .root -}}
{{- $out := list -}}
{{- if $root.Values.tenants -}}
{{- include "offerowl.validateTenants" $root -}}
{{- range $t := $root.Values.tenants -}}
{{- $name := toString (get $t "name") -}}
{{- $own := deepCopy (omit $t "name" "ingress" "extraEnv") -}}
{{- $values := mergeOverwrite (deepCopy (omit $root.Values "tenants")) $own -}}
{{- $_ := set $values "extraEnv" (concat ($root.Values.extraEnv | default list) (get $t "extraEnv" | default list)) -}}
{{- $ingress := get $t "ingress" | default dict -}}
{{- $host := get $ingress "host" | default (replace "{name}" $name (toString ($root.Values.ingress.tenantHost | default ""))) -}}
{{- $annotations := merge (deepCopy (get $ingress "annotations" | default dict)) ($root.Values.ingress.annotations | default dict) -}}
{{- $_ := set $values "tenantIngress" (dict "host" $host "annotations" $annotations "tls" (get $ingress "tls" | default $root.Values.ingress.tls)) -}}
{{- $out = append $out (dict "Values" $values "Release" $root.Release "Chart" $root.Chart "Tenant" $name) -}}
{{- end -}}
{{- else -}}
{{- $out = append $out (dict "Values" $root.Values "Release" $root.Release "Chart" $root.Chart "Tenant" "") -}}
{{- end -}}
{{- $_ := set .holder "instances" $out -}}
{{- end -}}

{{/*
The people of tenants, refused before anything is rendered when they cannot work side by side: a name that is no DNS
label, a name twice, a field that is not a person's (a typo would be silently ignored), one claim for two people, the
release's existingClaim (every person would share it), an Ingress host missing or twice, or names past 63 characters.
*/}}
{{- define "offerowl.validateTenants" -}}
{{- $allowed := list "name" "ai" "resources" "persistence" "language" "timezone" "extraEnv" "ingress" "podAnnotations" "nodeSelector" "tolerations" "affinity" -}}
{{- $names := list -}}
{{- $claims := list -}}
{{- $hosts := list -}}
{{- if .Values.persistence.existingClaim -}}
{{- fail "persistence.existingClaim cannot be set for the whole release with tenants: every person would share one claim. Set tenants[].persistence.existingClaim for the one person it belongs to." -}}
{{- end -}}
{{- range $i, $t := .Values.tenants -}}
{{- if not (kindIs "map" $t) -}}
{{- fail (printf "tenants[%d] must be a map with at least a name, for example {name: alice}" $i) -}}
{{- end -}}
{{- $name := toString (get $t "name") -}}
{{- if not (regexMatch "^[a-z0-9]([-a-z0-9]*[a-z0-9])?$" $name) -}}
{{- fail (printf "tenants[%d].name %q must be a DNS label: lower-case letters, digits and -, starting and ending with a letter or a digit" $i $name) -}}
{{- end -}}
{{- if has $name $names -}}
{{- fail (printf "tenants: %q is listed twice; each person needs a name of their own" $name) -}}
{{- end -}}
{{- $names = append $names $name -}}
{{- range $key, $_ := $t -}}
{{- if not (has $key $allowed) -}}
{{- fail (printf "tenants[%d] (%s) has %q, which is not a person's own setting; these are: %s" $i $name $key (join ", " $allowed)) -}}
{{- end -}}
{{- end -}}
{{- $full := printf "%s-%s-data" (include "offerowl.fullname" $) $name -}}
{{- if gt (len $full) 63 -}}
{{- fail (printf "tenants[%d].name %q is too long for this release: %q passes the 63 characters Kubernetes allows. Use a shorter name or fullnameOverride." $i $name $full) -}}
{{- end -}}
{{- $claim := get (get $t "persistence" | default dict) "existingClaim" | default "" -}}
{{- if $claim -}}
{{- if has $claim $claims -}}
{{- fail (printf "tenants: the claim %q is named for two people; each person's documents need a claim of their own" $claim) -}}
{{- end -}}
{{- $claims = append $claims $claim -}}
{{- end -}}
{{- if $.Values.ingress.enabled -}}
{{- $host := get (get $t "ingress" | default dict) "host" | default (replace "{name}" $name (toString ($.Values.ingress.tenantHost | default ""))) -}}
{{- if or (not $host) (eq $host (toString ($.Values.ingress.tenantHost | default ""))) -}}
{{- fail (printf "tenants[%d] (%s) has no host name for the Ingress: set ingress.tenantHost with {name} in it (for example {name}.offerowl.example.com), or tenants[].ingress.host" $i $name) -}}
{{- end -}}
{{- if has $host $hosts -}}
{{- fail (printf "tenants: the host %q is given to two people; the Ingress would send them to one panel" $host) -}}
{{- end -}}
{{- $hosts = append $hosts $host -}}
{{- end -}}
{{- end -}}
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

{{/* The claim the data folder lives on: the one you name, or the one the chart makes (one per person with tenants). */}}
{{- define "offerowl.claimName" -}}
{{- .Values.persistence.existingClaim | default (printf "%s-data" (include "offerowl.instanceName" .)) -}}
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
{{- $who := "" -}}
{{- if .Tenant -}}
{{- $who = printf "tenants (%s): " .Tenant -}}
{{- end -}}
{{- $backend := toString .Values.ai.backend -}}
{{- if not (has $backend (list "none" "openai-compat")) -}}
{{- fail (printf "%sai.backend must be none or openai-compat, not %q. Claude Code and Codex are not in the image: stay signed in to them on your own PC, or use a local model server." $who $backend) -}}
{{- end -}}
{{- if and (eq $backend "openai-compat") (not .Values.ai.url) -}}
{{- fail (printf "%sai.backend=openai-compat needs ai.url, the address of the model server (for example http://ollama.models.svc:11434)" $who) -}}
{{- end -}}
{{- if and .Values.ai.existingSecret (not .Values.ai.secretKey) -}}
{{- fail (printf "%sai.existingSecret needs ai.secretKey, the name of the key inside that Secret" $who) -}}
{{- end -}}
{{- $panel := int .Values.service.panelPort -}}
{{- if or (lt $panel 1024) (gt $panel 65535) -}}
{{- fail "service.panelPort must be between 1024 and 65535: the pod does not run as root, so it cannot listen on a lower port" -}}
{{- end -}}
{{- if and .Values.ingress.enabled (not .Tenant) (not .Values.ingress.hosts) -}}
{{- fail "ingress.enabled needs at least one entry in ingress.hosts" -}}
{{- end -}}
{{- $reserved := list "OFFEROWL_PANEL_PORT" "OFFEROWL_DATA_DIR" "OFFEROWL_LLM" "OFFEROWL_LLM_URL" "OFFEROWL_LLM_MODEL" "OFFEROWL_LLM_KEY" "OFFEROWL_ALLOWED_HOSTS" "OFFEROWL_DESKTOP" "OFFEROWL_LANG" "HOME" "TZ" -}}
{{- range $var := .Values.extraEnv -}}
{{- if has (toString $var.name) $reserved -}}
{{- fail (printf "%sextraEnv may not set %s: the chart or the image sets it (values.yaml, extraEnv)" $who $var.name) -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
The Ingress' host names as one comma-separated list, the form of OFFEROWL_ALLOWED_HOSTS: a person's own host alone with
tenants (their panel refuses every other person's name), else every host of ingress.hosts.
*/}}
{{- define "offerowl.ingressHosts" -}}
{{- if .Tenant -}}
{{- .Values.tenantIngress.host -}}
{{- else -}}
{{- $hosts := list -}}
{{- range .Values.ingress.hosts -}}
{{- $hosts = append $hosts .host -}}
{{- end -}}
{{- join "," $hosts -}}
{{- end -}}
{{- end -}}
