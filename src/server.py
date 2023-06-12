import json
import falcon
import datetime

from wsgiref.simple_server import make_server
from kubernetes.client.rest import ApiException
import kubernetes.client, kubernetes.config

from src.setup import get_settings, throw_if_setting_not_set

class HookResource:
    def on_post(self, req, resp):
        """Handles POST requests"""

        if req.content_type != 'application/json':
            raise falcon.HTTPUnsupportedMediaType(title='Unsupported content type',
                                                    description='Use application/json.')
        
        if req.content_length in (None, 0):
            raise falcon.HTTPBadRequest(title='Empty request body',
                                        description='A valid JSON document is required.')

        token = req.get_header('Authorization')
        if token is None:
            raise falcon.HTTPUnauthorized(title='Unauthorized',
                                            description='Missing token.')

        # parse the body
        body = req.bounded_stream.read()
        if not body:
            raise falcon.HTTPBadRequest(title='Empty request body',
                                        description='A valid JSON document is required.')
        
        # parse the body
        try:
            req_body = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise falcon.HTTPError(code=falcon.HTTP_753,
                                    title='Malformed JSON',
                                    description='Could not decode the request body. The '
                                                'JSON was incorrect or not encoded as '
                                                'UTF-8.')
        
        throw_if_not_set('type', req_body)
        throw_if_not_set('event_data', req_body)
        throw_if_not_set('event_data.repository', req_body)
        throw_if_not_set('event_data.repository.namespace', req_body)
        throw_if_not_set('event_data.repository.name', req_body)

        if req_body["type"] != "PUSH_ARTIFACT":
            raise falcon.HTTPBadRequest(title='Invalid event type',
                                        description='Event type is not supported.')
        
        cluster_name = req.params.get('cluster')
        if cluster_name is None:
            raise falcon.HTTPBadRequest(title='Invalid cluster',
                                        description='Cluster is not specified.')

        # project_name -> k8s namespace
        # repo_name -> k8s deployment
        project_name = req_body["event_data"]["repository"]["namespace"]
        repo_name = req_body["event_data"]["repository"]["name"]

        # get k8s client
        client = None
        for cluster in get_settings()['k8s']:
            if cluster['name'] == cluster_name:
                client = cluster['client']
                break
        
        if client is None:
            raise falcon.HTTPBadRequest(title='Invalid cluster',
                                        description='Cluster is not found.')        
        
        apiV1 = kubernetes.client.CoreV1Api(client)
        appsV1 = kubernetes.client.AppsV1Api(client)

        # get namespace
        namespace = None
        for ns in apiV1.list_namespace().items:
            if ns.metadata.name == project_name:
                namespace = ns
                break

        if namespace is None:
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
            raise falcon.HTTPBadRequest(title='Invalid secret',
                                        description='Secret is not found.')
        
        if secret.data['token'] != token:
            raise falcon.HTTPUnauthorized(title='Unauthorized',
                                            description='Invalid token.')

        # get deployment
        deployment = None
        for d in appsV1.list_namespaced_deployment(namespace.metadata.name).items:
            if d.metadata.name == repo_name:
                deployment = d
                break
        
        if deployment is None:
            raise falcon.HTTPBadRequest('Invalid deployment',
                                        'Deployment is not found.')
        
        # restart deployment
        _restart_deployment(appsV1, deployment.metadata.name, namespace.metadata.name)
    
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

def throw_if_not_set(key, json_body):
    split = key.split('.')
    parent = json_body
    
    for i in range(len(split)):
        if split[i] not in parent:
            raise falcon.HTTPBadRequest(title='Invalid request body',
                                        description=f'Key {key} is required.')

        if parent[split[i]] == None:
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