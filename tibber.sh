
# Replace the provided demo token with your own:
# https://developer.tibber.com/settings/accesstoken
curl \
    -H "Authorization: Bearer 476c477d8a039529478ebd690d35ddd80e3308ffc49b59c65b142321aee963a4" \
    -H "Content-Type: application/json" \
    -X POST \
    -d  '{ "query": "{viewer {homes { id }}}" }' \
    https://api.tibber.com/v1-beta/gql
