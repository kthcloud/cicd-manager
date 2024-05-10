curl -X POST http://localhost:8080/v1/hook\?cluster\=sys \
-H "Content-Type: application/json" -H "Authorization: <secret>" \
-d '{
    "type":"PUSH_ARTIFACT",
    "event_data": {
        "resources": [
            {
                "resource_url": "registry.cloud.cbh.kth.se/deploy/deploy:latest"
            }
        ],
        "repository": {
            "name": "deploy",
            "namespace": "deploy"
        }
    }
}'