# 🤖 kthcloud/cicd-manager

CI/CD Manager for kthcloud automatically restarts Kubernetes deployments when a new image is pushed to the registry.

## 🌐 API
/v1/hook - Webhook endpoint for pushed images

## 🔧 Usage
In order to use the CI/CD Manager, you need to create a Kubernetes secret called `kthcloud-ci-token` in the namespace you want to use it in. The secret should contain a base64 encoded token called `token`. The token is used to authenticate the webhook endpoint.

Example secret:
```yaml
kind: Secret
apiVersion: v1
metadata:
  name: kthcloud-ci-token
  namespace: <your namespace>
data:
  token: <base64 encoded token>
type: Opaque
```
