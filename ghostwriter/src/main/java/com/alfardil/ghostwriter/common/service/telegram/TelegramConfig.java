package com.alfardil.ghostwriter.common.service.telegram;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
class TelegramConfig {

  @Bean
  RestClient telegramClient(@Value("${app.telegram.bot-token}") String token) {
    return RestClient.builder()
      .baseUrl("https://api.telegram.org/bot" + token)
      .build();
  }
}
