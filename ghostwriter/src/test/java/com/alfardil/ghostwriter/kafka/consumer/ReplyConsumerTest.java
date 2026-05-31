package com.alfardil.ghostwriter.kafka.consumer;

import static org.mockito.Mockito.verify;

import com.alfardil.ghostwriter.common.service.telegram.TelegramService;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ReplyConsumerTest {

  @Mock
  private TelegramService telegramService;

  @InjectMocks
  private ReplyConsumer replyConsumer;

  @Test
  @DisplayName("Reply record is forwarded to Telegram")
  void consume() {
    ConsumerRecord<String, String> record = new ConsumerRecord<>(
      "reply",
      0,
      0L,
      "user123",
      "AI response"
    );

    replyConsumer.consume(record);

    verify(telegramService).sendMessage("user123", "AI response");
  }
}
