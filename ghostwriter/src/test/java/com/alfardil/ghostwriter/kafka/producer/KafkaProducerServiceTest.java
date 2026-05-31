package com.alfardil.ghostwriter.kafka.producer;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.concurrent.CompletableFuture;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.apache.kafka.common.TopicPartition;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

@ExtendWith(MockitoExtension.class)
class KafkaProducerServiceTest {

  @Mock
  private KafkaTemplate<String, String> kafkaTemplate;

  @InjectMocks
  private KafkaProducerService kafkaProducerService;

  @Test
  @DisplayName("sendMessage publishes to the task topic")
  void sendMessage() {
    RecordMetadata metadata = new RecordMetadata(
      new TopicPartition("task", 0),
      0L,
      0,
      System.currentTimeMillis(),
      0,
      0
    );
    SendResult<String, String> sendResult = mock(SendResult.class);
    when(sendResult.getRecordMetadata()).thenReturn(metadata);
    when(kafkaTemplate.send("task", "user1", "hello")).thenReturn(
      CompletableFuture.completedFuture(sendResult)
    );

    kafkaProducerService.sendMessage("user1", "hello");

    verify(kafkaTemplate).send("task", "user1", "hello");
  }

  @Test
  @DisplayName("sendMessage swallows Kafka failure")
  void sendMessageKafkaFailure() {
    when(kafkaTemplate.send(anyString(), anyString(), anyString())).thenReturn(
      CompletableFuture.failedFuture(new RuntimeException("Kafka down"))
    );

    assertThatCode(() ->
      kafkaProducerService.sendMessage("user1", "hello")
    ).doesNotThrowAnyException();
  }

  @Test
  @DisplayName("sendReply publishes to the reply topic")
  void sendReply() {
    RecordMetadata metadata = new RecordMetadata(
      new TopicPartition("reply", 0),
      0L,
      0,
      System.currentTimeMillis(),
      0,
      0
    );
    SendResult<String, String> sendResult = mock(SendResult.class);
    when(sendResult.getRecordMetadata()).thenReturn(metadata);
    when(kafkaTemplate.send("reply", "user1", "response")).thenReturn(
      CompletableFuture.completedFuture(sendResult)
    );

    kafkaProducerService.sendReply("user1", "response");

    verify(kafkaTemplate).send("reply", "user1", "response");
  }

  @Test
  @DisplayName("sendReply swallows Kafka failure")
  void sendReplyKafkaFailure() {
    when(kafkaTemplate.send(anyString(), anyString(), anyString())).thenReturn(
      CompletableFuture.failedFuture(new RuntimeException("Kafka down"))
    );

    assertThatCode(() ->
      kafkaProducerService.sendReply("user1", "response")
    ).doesNotThrowAnyException();
  }
}
