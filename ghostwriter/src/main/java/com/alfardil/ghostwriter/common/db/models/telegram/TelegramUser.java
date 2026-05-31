package com.alfardil.ghostwriter.common.db.models.telegram;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;

@JsonIgnoreProperties(ignoreUnknown = true)
@Getter
public class TelegramUser {

    @JsonProperty("id")
    private Long id;

    @JsonProperty("username")
    private String username;
}
