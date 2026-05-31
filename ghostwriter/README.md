Curl quickstart for Gemini AI:

```bash
curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent" \
  -H 'Content-Type: application/json' \
  -H 'X-goog-api-key: ${GEMINI_API_KEY}' \
  -X POST \
  -d '{
    "contents": [
      {
        "parts": [
          {
            "text": "Explain how AI works in a few words"
          }
        ]
      }
    ]
  }'
```

For naming variables, we use camelCase.

Using [Aiven](https://console.aiven.io/account/a5aea1a676cb/project/ghostwriter/services/ghostwriter-kafka/overview) for Kafka.
