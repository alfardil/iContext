package com.alfardil.ghostwriter.common.service.telegram;

import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

@Service
public class TelegramService {

  private static final Logger log = LoggerFactory.getLogger(
    TelegramService.class
  );
  private final RestClient restClient;

  public TelegramService(RestClient telegramClient) {
    this.restClient = telegramClient;
  }

  public void sendMessage(String userId, String unsafeText) {
    String text =
      unsafeText.length() >= 4000
        ? unsafeText.substring(0, 4000) + "...(truncated)"
        : unsafeText;

    try {
      post(userId, text, "HTML");
      log.info("Telegram reply sent (HTML)");
    } catch (Exception htmlErr) {
      log.warn(
        "Telegram HTML send failed (likely malformed tags) — retrying as plain text. userId={} | error={}",
        userId,
        htmlErr.getMessage()
      );
      try {
        post(userId, text, null);
        log.info("Telegram reply sent (plain text fallback)");
      } catch (Exception plainErr) {
        log.error(
          "Telegram reply send failed with userId={} | error={}",
          userId,
          plainErr.getMessage()
        );
      }
    }
  }

  private void post(String userId, String text, String parseMode) {
    Map<String, Object> body = parseMode == null
      ? Map.of("chat_id", userId, "text", text)
      : Map.of("chat_id", userId, "text", text, "parse_mode", parseMode);

    restClient
      .post()
      .uri("/sendMessage")
      .contentType(MediaType.APPLICATION_JSON)
      .body(body)
      .retrieve()
      .toBodilessEntity();
  }
}
