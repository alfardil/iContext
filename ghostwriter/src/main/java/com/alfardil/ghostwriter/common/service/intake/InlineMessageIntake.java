package com.alfardil.ghostwriter.common.service.intake;

import com.alfardil.ghostwriter.common.service.agent.ConversationService;
import com.alfardil.ghostwriter.common.service.telegram.TelegramService;
import jakarta.annotation.PreDestroy;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/**
 * Prod ingress: no broker. The webhook hands the message to a small background pool, which runs
 * the LLM turn and delivers the reply to Telegram directly. This keeps the 1 GB box free of a
 * Kafka JVM (see DEPLOYMENT.md) while preserving the key property of the old two-topic design —
 * the webhook returns 200 fast and the slow AI work happens out of band.
 *
 * <p>On failure we log and drop (we already 200'd the webhook). That's deliberate: a single user
 * doesn't need delivery retries, and not retrying a failed Anthropic call avoids burning credits —
 * the same concern the Kafka error handler addressed in dev.
 */
@Slf4j
@Component
@Profile("prod")
public class InlineMessageIntake implements MessageIntake {

  private final ConversationService conversationService;
  private final TelegramService telegramService;
  private final ExecutorService executor;

  public InlineMessageIntake(
    final ConversationService conversationService,
    final TelegramService telegramService
  ) {
    this.conversationService = conversationService;
    this.telegramService = telegramService;
    this.executor = Executors.newFixedThreadPool(2, runnable -> {
      Thread thread = new Thread(runnable, "inline-intake");
      thread.setDaemon(true);
      return thread;
    });
  }

  @Override
  public void accept(String userId, String userMessage) {
    executor.submit(() -> {
      try {
        String aiResponse = conversationService.respond(userId, userMessage);
        telegramService.sendMessage(userId, aiResponse);
      } catch (Exception e) {
        log.error("inline processing failed for userId={}: {}", userId, e.getMessage(), e);
      }
    });
  }

  @PreDestroy
  public void shutdown() {
    executor.shutdown();
  }
}
