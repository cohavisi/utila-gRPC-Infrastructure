{{- define "greeter.settings" -}}
{{- toYaml .Values.settings -}}
{{- end -}}

{{- define "greeter.bootstrap" -}}
- name: xds-bootstrap
  image: {{ .root.Values.bootstrapImage | quote }}
  args:
    - --gcp-project-number=$(PROJECT_NUMBER)
    - --config-mesh=$(MESH_NAME)
    - --vpc-network-name=$(NETWORK_NAME)
    - --locality-zone=$(ZONE)
    - --gke-cluster-name=$(CLUSTER_NAME)
    - --gke-location-experimental=$(ZONE)
    - --gke-namespace-experimental=$(POD_NAMESPACE)
    - --gke-pod-name-experimental=$(POD_NAME)
    - --output=/bootstrap/bootstrap.json
    - --node-metadata=app={{ if eq .role "server" }}greeter{{ else }}greeter-client{{ end }}
  envFrom:
    - configMapRef:
        name: deployment-settings
  env:
    - name: POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    - name: POD_NAMESPACE
      valueFrom:
        fieldRef:
          fieldPath: metadata.namespace
  volumeMounts:
    - name: bootstrap
      mountPath: /bootstrap
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: ["ALL"]
  resources:
    requests:
      cpu: 50m
      memory: 32Mi
    limits:
      cpu: 250m
      memory: 64Mi
{{- end -}}
