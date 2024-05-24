import json
import falcon
import datetime

from wsgiref.simple_server import make_server
from kubernetes.client.rest import ApiException
import kubernetes.client, kubernetes.config

from src.setup import get_settings

class HookResource:
    def on_post(self, req, resp):
        """Handles POST requests"""

        if req.content_type != 'application/json':
            print(f'Invalid content type: {req.content_type}')
            raise falcon.HTTPUnsupportedMediaType(title='Unsupported content type',
                                                    description='Use application/json.')
        
        if req.content_length in (None, 0):
            print(f'Empty request body. A valid JSON document is required.')
            raise falcon.HTTPBadRequest(title='Empty request body',
                                        description='A valid JSON document is required.')

        token = req.get_header('Authorization')
        if token is None:
            print(f'Unauthorized: Missing token')            
            raise falcon.HTTPUnauthorized(title='Unauthorized',
                                            description='Missing token.')

        # parse the body
        body = req.bounded_stream.read()
        if not body:
            print(f'Empty request body. A valid JSON document is required.')
            raise falcon.HTTPBadRequest(title='Empty request body',
                                        description='A valid JSON document is required.')
        
        # parse the body
        try:
            req_body = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            print(f'Could not decode the request body. The JSON was incorrect or not encoded as UTF-8.')
            raise falcon.HTTPBadRequest(code=falcon.HTTP_400,
                                    title='Malformed JSON',
                                    description='Could not decode the request body. The '
                                                'JSON was incorrect or not encoded as '
                                                'UTF-8.')
        
        throw_if_not_set('type', req_body)
        throw_if_not_set('event_data', req_body)
        throw_if_not_set('event_data.repository', req_body)
        throw_if_not_set('event_data.repository.namespace', req_body)
        throw_if_not_set('event_data.repository.name', req_body)
        throw_if_not_set('event_data.resources', req_body)
        if len(req_body['event_data']['resources']) == 0:
            raise falcon.HTTPBadRequest(title='Invalid request body',
                                        description='event_data.resources is empty.')

        throw_if_not_set('resource_url', req_body['event_data']['resources'][0])

        if req_body["type"] != "PUSH_ARTIFACT":
            print(f'Invalid event type: {req_body["type"]}')
            raise falcon.HTTPBadRequest(title='Invalid event type',
                                        description='Event type is not supported.')
        
        cluster_name = req.params.get('cluster')
        if cluster_name is None:
            print(f'Invalid cluster. Cluster is not specified')
            raise falcon.HTTPBadRequest(title='Invalid cluster',
                                        description='Cluster is not specified.')

        custom_namespace = req.params.get('namespace')
        if custom_namespace is not None:
            project_name = custom_namespace
        else:        
            project_name = req_body["event_data"]["repository"]["namespace"]

        # project_name -> k8s namespace
        # repo_name -> k8s deployment

        # get k8s client
        client = get_client(cluster_name)        
        if client is None:
            print(f'Cluster {cluster_name} is not found, or no client exists for it')
            raise falcon.HTTPBadRequest(title='Invalid cluster',
                                        description=f'Cluster {cluster_name} is not found, or no client exists for it.')        
        
        apiV1 = kubernetes.client.CoreV1Api(client)
        appsV1 = kubernetes.client.AppsV1Api(client)

        # get namespace
        namespace = None
        for ns in apiV1.list_namespace().items:
            if ns.metadata.name == project_name:
                namespace = ns
                break

        if namespace is None:
            print(f'Namespace {project_name} does not exist')
            raise falcon.HTTPBadRequest(title='Invalid namespace',
                                        description='Namespace is not found.')
        
        
        # get secret
        secret_name = "kthcloud-ci-token"
        secret = None
        for s in apiV1.list_namespaced_secret(namespace.metadata.name).items:
            if s.metadata.name == secret_name:
                secret = s
                break

        if secret is None:
            print(f'Secret {secret_name} does not exist in namespace {namespace.metadata.name}')
            raise falcon.HTTPBadRequest(title='Invalid secret',
                                        description='Secret is not found.')
        
        if 'token' not in secret.data:
            print(f'Secret {secret_name} does not contain a token field in namespace {namespace.metadata.name}')
            raise falcon.HTTPBadRequest(title='Invalid secret',
                                        description='Secret is not found.')
        
        if secret.data['token'] != token:
            print(f'Unauthorized: Invalid token in namespace {namespace.metadata.name}')
            raise falcon.HTTPUnauthorized(title='Unauthorized',
                                            description='Invalid token.')

        # restart any deployment using the image
        image = req_body['event_data']['resources'][0]['resource_url']

        # We also match if the image is tagged with latest, and the deployment does not use a tag (implicit latest)
        harbor_image_is_latests = image.endswith(":latest") or len(image.split(":")) == 1
        
        deployments = []
        statefulsets = []

        for d in appsV1.list_namespaced_deployment(namespace.metadata.name).items:
            for c in d.spec.template.spec.containers:
                # match image name
                if c.image == image:
                    deployments.append(d)
                    break                

                deployment_image_is_latest = c.image.endswith(":latest") or len(c.image.split(":")) == 1

                if harbor_image_is_latests and deployment_image_is_latest and image.split(":")[0] == c.image.split(":")[0]:
                    deployments.append(d)
                    break

        for s in appsV1.list_namespaced_stateful_set(namespace.metadata.name).items:
            for c in s.spec.template.spec.containers:
                # match image name
                if c.image == image:
                    statefulsets.append(s)
                    break                

                statefulset_image_is_latest = c.image.endswith(":latest") or len(c.image.split(":")) == 1

                if harbor_image_is_latests and statefulset_image_is_latest and image.split(":")[0] == c.image.split(":")[0]:
                    statefulsets.append(s)
                    break
        
        
        if len(deployments) == 0:
            print(f'No deployment is using image {image} in namespace {namespace.metadata.name}')
        else:
            # restart deployment
            for deployment in deployments:
                print(f'Restarting deployment {deployment.metadata.name} in namespace {namespace.metadata.name}')
                _restart_deployment(appsV1, deployment.metadata.name, namespace.metadata.name)
    
        if len(statefulsets) == 0:
            print(f'No statefulset is using image {image} in namespace {namespace.metadata.name}')
        else:
            # restart statefulset
            for statefulset in statefulsets:
                print(f'Restarting statefulset {statefulset.metadata.name} in namespace {namespace.metadata.name}')
                _restart_statefulset(appsV1, statefulset.metadata.name, namespace.metadata.name)


        resp.status = falcon.HTTP_200

def _restart_deployment(v1_apps, deployment, namespace):
    now = datetime.datetime.utcnow()
    now = str(now.isoformat("T") + "Z")
    body = {
        'spec': {
            'template':{
                'metadata': {
                    'annotations': {
                        'kubectl.kubernetes.io/restartedAt': now
                    }
                }
            }
        }
    }
    try:
        v1_apps.patch_namespaced_deployment(deployment, namespace, body, pretty='true')
    except ApiException as e:
        print("Exception when calling AppsV1Api->read_namespaced_deployment_status: %s\n" % e)

def _restart_statefulset(v1_apps, statefulset, namespace):
    now = datetime.datetime.utcnow()
    now = str(now.isoformat("T") + "Z")
    body = {
        'spec': {
            'template':{
                'metadata': {
                    'annotations': {
                        'kubectl.kubernetes.io/restartedAt': now
                    }
                }
            }
        }
    }
    try:
        v1_apps.patch_namespaced_stateful_set(statefulset, namespace, body, pretty='true')
    except ApiException as e:
        print("Exception when calling AppsV1Api->read_namespaced_stateful_set_status: %s\n" % e)


def get_client(cluster_name):
    for cluster in get_settings()['k8s']['clusters']:
        if cluster['name'] == cluster_name:
            return cluster['client']
    
    return None

def throw_if_not_set(key, json_body):
    split = key.split('.')
    parent = json_body
    
    for i in range(len(split)):
        if split[i] not in parent:
            print(f"Invalid request body. Key {key} is required.")
            raise falcon.HTTPBadRequest(title='Invalid request body',
                                        description=f'Key {key} is required.')

        if parent[split[i]] == None:
            print(f"Invalid request body. Key {key} is required.")
            raise falcon.HTTPBadRequest('Invalid request body',
                                        f'Key {key} is required.')
        
        parent = parent[split[i]]

app = falcon.App()
app.add_route('/v1/hook', HookResource())

def run():
    with make_server('', 8080, app) as httpd:
        print('Serving on port 8080...')

        # Serve until process is killed
        httpd.serve_forever()