package com.alfardil.ghostwriter.common.service.intake;

/**
 * How an inbound Telegram message gets handed off for processing. The webhook returns 200
 * immediately and lets the intake do the slow work (LLM + delivery) out of band.
 *
 * <p>Two profile-scoped implementations: dev publishes to Kafka ({@code KafkaMessageIntake}),
 * prod runs inline on a background thread ({@code InlineMessageIntake}) so there's no broker to
 * host on a 1 GB box. See DEPLOYMENT.md.
 */
public interface MessageIntake {
  void accept(String userId, String userMessage);
}
