package com.alfardil.ghostwriter.common.service.agent;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.alfardil.ghostwriter.kafka.producer.KafkaProducerService;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class AgentServiceTest {

  @Mock
  private ConversationService conversationService;

  @Mock
  private KafkaProducerService kafkaProducerService;

  @InjectMocks
  private AgentService agentService;

  @Test
  @DisplayName("Valid message is processed and the reply is forwarded to the reply topic")
  void validMessage() {
    when(conversationService.respond("user123", "hello")).thenReturn("AI response");
    ConsumerRecord<String, String> record = new ConsumerRecord<>("task", 0, 0L, "user123", "hello");

    agentService.consume(record);

    verify(conversationService).respond("user123", "hello");
    verify(kafkaProducerService).sendReply("user123", "AI response");
  }

  @Test
  @DisplayName("Null message is ignored")
  void nullMessage() {
    ConsumerRecord<String, String> record = new ConsumerRecord<>("task", 0, 0L, "user123", null);

    agentService.consume(record);

    verifyNoInteractions(conversationService, kafkaProducerService);
  }

  @Test
  @DisplayName("Blank message is ignored")
  void blankMessage() {
    ConsumerRecord<String, String> record = new ConsumerRecord<>("task", 0, 0L, "user123", "   ");

    agentService.consume(record);

    verifyNoInteractions(conversationService, kafkaProducerService);
  }

  @Test
  @DisplayName("Processing exception is rethrown and no reply is sent")
  void processingThrows() {
    RuntimeException ex = new RuntimeException("boom");
    when(conversationService.respond(any(), any())).thenThrow(ex);
    ConsumerRecord<String, String> record = new ConsumerRecord<>("task", 0, 0L, "user123", "hello");

    assertThatThrownBy(() -> agentService.consume(record)).isSameAs(ex);

    verifyNoInteractions(kafkaProducerService);
  }
}
