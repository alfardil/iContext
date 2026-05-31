package com.alfardil.ghostwriter.kafka.producer;

import java.util.concurrent.CompletableFuture;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Profile;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.stereotype.Service;

@Service
@Profile("!prod")
public class KafkaProducerService {

  private static final Logger log = LoggerFactory.getLogger(
    KafkaProducerService.class
  );
  private static final String TASK_TOPIC = "task";
  private static final String REPLY_TOPIC = "reply";

  private final KafkaTemplate<String, String> kafkaTemplate;

  public KafkaProducerService(KafkaTemplate<String, String> kafkaTemplate) {
    this.kafkaTemplate = kafkaTemplate;
  }

  public void sendMessage(String userId, String message) {
    CompletableFuture<SendResult<String, String>> future = kafkaTemplate.send(
      TASK_TOPIC,
      userId,
      message
    );

    future.whenComplete((result, ex) -> {
      if (ex != null) {
        log.error(
          "Kafka send failed with userId {} and the following error {}",
          userId,
          ex.getMessage()
        );
      } else {
        log.info(
          "Kafka send fired | topic={} | partition={} | offset={} | userId={} | msg={}",
          result.getRecordMetadata().topic(),
          result.getRecordMetadata().partition(),
          result.getRecordMetadata().offset(),
          userId,
          message
        );
      }
    });
  }

  public void sendReply(String userId, String message) {
    CompletableFuture<SendResult<String, String>> future = kafkaTemplate.send(
      REPLY_TOPIC,
      userId,
      message
    );

    future.whenComplete((result, ex) -> {
      if (ex != null) {
        log.error(
          "Kafka reply send failed with userId of {} and the following error {}",
          userId,
          ex.getMessage()
        );
      } else {
        log.info(
          "Kafka reply fired | topic={} | partition={} | offset={} | userId={}",
          result.getRecordMetadata().topic(),
          result.getRecordMetadata().partition(),
          result.getRecordMetadata().offset(),
          userId
        );
      }
    });
  }
}
