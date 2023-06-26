import yaml
import os
import re

from cs import CloudStack
import kubernetes.client, kubernetes.config

settings = {}

def get_settings ():
    """Get settings from config file"""
    global settings
    if settings == {}:
        load_settings()
    return settings

def load_settings():
    """Load settings from config file"""

    env_name = "CONFIG_FILE"
    if env_name not in os.environ:
        raise Exception(f'{env_name} is not set')
    else:
        config_path = os.environ[env_name]

    yaml_file = open(config_path, 'r')
    
    global settings
    settings = yaml.load(yaml_file, Loader=yaml.FullLoader)

def load_kube_configs():

    settings = get_settings()

    throw_if_setting_not_set('cloudstack')
    throw_if_setting_not_set('cloudstack.apiKey')
    throw_if_setting_not_set('cloudstack.secret')
    throw_if_setting_not_set('cloudstack.url')
    throw_if_setting_not_set('k8s')    
    
    # fetch kubeconfigs from cloudstack for clusters system, prod, dev
    cs = CloudStack(settings['cloudstack']['url'], settings['cloudstack']['apiKey'], settings['cloudstack']['secret'])
    
    # fetch from cloudstack
    for idx, cluster in enumerate(settings['k8s']):
        try:
        
            # list all = true
            cluster_res = cs.listKubernetesClusters(name=cluster['name'], listall=True)
            
            if len(cluster_res['kubernetescluster']) == 0:
                print(f'Cluster {cluster["name"]} not found')
                continue

            # fetch kubeconfig
            id = cluster_res['kubernetescluster'][0]['id']
            config = cs.getKubernetesClusterConfig(id=id)

            # replace local ip with public ip
            regex = r'https://172.31.1.[0-9]+:6443'
            config = re.sub(regex, cluster['url'], config['clusterconfig']['configdata'], 0, re.MULTILINE)

            # add to settings
            settings['k8s'][idx]['config'] = config
        except:
            print(f'Failed to fetch kubeconfig for cluster {cluster["name"]}')


def load_k8s_clients():
    throw_if_setting_not_set('k8s')

    for idx, cluster in enumerate(get_settings()['k8s']):
        try:
            yaml_config = yaml.load(cluster['config'], Loader=yaml.FullLoader)

            client = kubernetes.config.new_client_from_config_dict(yaml_config)
            connected = __check_k8s_cluster_connection(client)
            if not connected:
                print(f'Cluster {cluster["name"]} not connected')
                continue

            settings['k8s'][idx]['client'] = client
        except:
            print(f'Failed to load k8s client for cluster {cluster["name"]}')

def throw_if_setting_not_set(key):
    split = key.split('.')
    parent = settings
    length = len(split) - 1
    for i in range(length):
        if parent[split[i]] == None:
            raise Exception(f'{key} is not set')
        
        parent = parent[split[i]]
    
def __check_k8s_cluster_connection(client):
    """Check if k8s cluster is connected"""
    namespaces = kubernetes.client.CoreV1Api(client).list_namespace()
    if namespaces == None:
        return False
    
    # check if kube-system is in the result
    for ns in namespaces.items:
        if ns.metadata.name == 'kube-system':
            return True
    
    return False
    
    
