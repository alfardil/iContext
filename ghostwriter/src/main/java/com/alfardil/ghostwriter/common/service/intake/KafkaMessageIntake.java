package com.alfardil.ghostwriter.common.service.intake;

import com.alfardil.ghostwriter.kafka.producer.KafkaProducerService;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/** Dev ingress: publish the message to the Kafka {@code task} topic for {@code AgentService}. */
@Component
@Profile("!prod")
public class KafkaMessageIntake implements MessageIntake {

  private final KafkaProducerService kafkaProducerService;

  public KafkaMessageIntake(final KafkaProducerService kafkaProducerService) {
    this.kafkaProducerService = kafkaProducerService;
  }

  @Override
  public void accept(String userId, String userMessage) {
    kafkaProducerService.sendMessage(userId, userMessage);
  }
}
