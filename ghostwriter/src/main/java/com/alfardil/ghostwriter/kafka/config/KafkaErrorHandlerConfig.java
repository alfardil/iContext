package com.alfardil.ghostwriter.kafka.config;

import com.anthropic.errors.AnthropicException;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.FixedBackOff;
import org.springframework.web.client.HttpClientErrorException;

@Configuration
@Profile("!prod")
public class KafkaErrorHandlerConfig {

  // Stop Spring Kafka from retrying client-side LLM errors (bad model, no credits, invalid key,
  // 4xx from MCP, etc.). Each retry would burn another Anthropic call against the same broken
  // state. Transient blips (5xx, network) still get two retries with a 1s backoff.
  @Bean
  public DefaultErrorHandler kafkaErrorHandler() {
    DefaultErrorHandler handler = new DefaultErrorHandler(new FixedBackOff(1000L, 2));
    handler.addNotRetryableExceptions(
      AnthropicException.class,
      HttpClientErrorException.class
    );
    return handler;
  }
}
