package com.alfardil.ghostwriter.common.db.models.telegram;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;

@JsonIgnoreProperties(ignoreUnknown = true)
@Getter
public class TelegramMessage {

    @JsonProperty("message_id")
    private Long messageId;

    @JsonProperty("text")
    private String text;

    @JsonProperty("from")
    private TelegramUser from;
}
