package com.alfardil.ghostwriter.common.service.telegram;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestClient;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class TelegramServiceTest {

  @Mock
  private RestClient restClient;

  @Mock
  private RestClient.RequestBodyUriSpec requestBodyUriSpec;

  @Mock
  private RestClient.RequestBodySpec requestBodySpec;

  @Mock
  private RestClient.ResponseSpec responseSpec;

  @InjectMocks
  private TelegramService telegramService;

  @BeforeEach
  void setUp() {
    when(restClient.post()).thenReturn(requestBodyUriSpec);
    when(requestBodyUriSpec.uri(anyString())).thenReturn(requestBodySpec);
    when(requestBodySpec.contentType(any())).thenReturn(requestBodySpec);
    when(requestBodySpec.body(any(Object.class))).thenReturn(requestBodySpec);
    when(requestBodySpec.retrieve()).thenReturn(responseSpec);
    when(responseSpec.toBodilessEntity()).thenReturn(ResponseEntity.ok().build());
  }

  @Test
  @DisplayName("Short message is sent as-is with HTML parse_mode")
  @SuppressWarnings("unchecked")
  void shortMessage() {
    telegramService.sendMessage("123", "Hello!");

    ArgumentCaptor<Map<String, Object>> bodyCaptor = ArgumentCaptor.forClass(Map.class);
    verify(requestBodySpec).body(bodyCaptor.capture());
    Map<String, Object> body = bodyCaptor.getValue();
    assertThat(body.get("chat_id")).isEqualTo("123");
    assertThat(body.get("text")).isEqualTo("Hello!");
    assertThat(body.get("parse_mode")).isEqualTo("HTML");
  }

  @Test
  @DisplayName("Message over 4000 chars is truncated")
  @SuppressWarnings("unchecked")
  void longMessageTruncated() {
    telegramService.sendMessage("123", "a".repeat(5000));

    ArgumentCaptor<Map<String, Object>> bodyCaptor = ArgumentCaptor.forClass(Map.class);
    verify(requestBodySpec).body(bodyCaptor.capture());
    String sentText = (String) bodyCaptor.getValue().get("text");
    assertThat(sentText).endsWith("...(truncated)");
    assertThat(sentText).hasSize(4014);
  }

  @Test
  @DisplayName("Message of exactly 4000 chars is truncated")
  @SuppressWarnings("unchecked")
  void exactLimitTruncated() {
    telegramService.sendMessage("123", "a".repeat(4000));

    ArgumentCaptor<Map<String, Object>> bodyCaptor = ArgumentCaptor.forClass(Map.class);
    verify(requestBodySpec).body(bodyCaptor.capture());
    assertThat((String) bodyCaptor.getValue().get("text")).endsWith("...(truncated)");
  }

  @Test
  @DisplayName("RestClient exception is swallowed")
  void restClientThrows() {
    when(restClient.post()).thenThrow(new RuntimeException("Connection refused"));

    assertThatCode(() -> telegramService.sendMessage("123", "Hello"))
      .doesNotThrowAnyException();
  }

  @Test
  @DisplayName("Sends to /sendMessage endpoint")
  void correctEndpoint() {
    telegramService.sendMessage("123", "Hello");

    verify(requestBodyUriSpec).uri("/sendMessage");
  }
}
