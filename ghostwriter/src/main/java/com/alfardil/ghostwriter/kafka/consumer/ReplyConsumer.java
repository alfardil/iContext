package com.alfardil.ghostwriter.kafka.consumer;

import com.alfardil.ghostwriter.common.service.telegram.TelegramService;
import lombok.extern.slf4j.Slf4j;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.context.annotation.Profile;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@Profile("!prod")
public class ReplyConsumer {

    private final TelegramService telegramService;

    public ReplyConsumer(TelegramService telegramService) {
        this.telegramService = telegramService;
    }

    @KafkaListener(topics = "reply", groupId = "ghostwriter-reply-consumer-group")
    public void consume(ConsumerRecord<String, String> record) {
        String userId = record.key();
        String aiResponse = record.value();

        log.info("Sending reply to userId={}", userId);
        telegramService.sendMessage(userId, aiResponse);
    }
}
