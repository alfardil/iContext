package com.alfardil.ghostwriter.common.service.agent;

import com.alfardil.ghostwriter.kafka.producer.KafkaProducerService;
import lombok.extern.slf4j.Slf4j;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.context.annotation.Profile;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;

@Slf4j
@Service
@Profile("!prod")
public class AgentService {

  private final ConversationService conversationService;
  private final KafkaProducerService kafkaProducerService;

  public AgentService(
    final ConversationService conversationService,
    final KafkaProducerService kafkaProducerService
  ) {
    this.conversationService = conversationService;
    this.kafkaProducerService = kafkaProducerService;
  }

  @KafkaListener(topics = "task", groupId = "ghostwriter-agent-consumer-group")
  public void consume(ConsumerRecord<String, String> record) {
    String userId = record.key();
    String userMessage = record.value();

    if (userMessage == null || userMessage.trim().isEmpty()) {
      log.warn("Received an empty message");
      return;
    }

    try {
      String aiResponse = conversationService.respond(userId, userMessage);
      kafkaProducerService.sendReply(userId, aiResponse);
    } catch (Exception e) {
      log.error("Failed to process message for userId={}: {}", userId, e.getMessage(), e);
      throw e;
    }
  }
}
