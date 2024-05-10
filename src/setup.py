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

    throw_if_setting_not_set('k8s')
    throw_if_setting_not_set('k8s.configDir')

    settings['k8s']['clusters'] = []
    
    # Load all configs from the configDir. The name of the file is the name of the cluster
    for file in os.listdir(settings['k8s']['configDir']):
        with open(f'{settings["k8s"]["configDir"]}/{file}', 'r') as f:
            config = f.read()
            settings['k8s']['clusters'].append({'name': file.split('.')[0], 'config': config})

    if len(settings['k8s']['clusters']) == 0:
        print('No kubeconfig found in the configDir! If this is not intended, please check the configDir path in the config file')
    else:
        print(f'Loaded {len(settings["k8s"]["clusters"])} kubeconfigs')

def load_k8s_clients():
    throw_if_setting_not_set('k8s')

    for idx, cluster in enumerate(get_settings()['k8s']['clusters']):
        try:
            yaml_config = yaml.load(cluster['config'], Loader=yaml.FullLoader)

            client = kubernetes.config.new_client_from_config_dict(yaml_config)
            connected = __check_k8s_cluster_connection(client)
            if not connected:
                print(f'Cluster {cluster["name"]} not connected')
                continue

            settings['k8s']['clusters'][idx]['client'] = client
        except Exception as e:
            print(f'Failed to load k8s client for cluster {cluster["name"]} with error: {e}')

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
    
    # Check if kube-system is in the result
    for ns in namespaces.items:
        if ns.metadata.name == 'kube-system':
            return True
    
    return False
    
    
