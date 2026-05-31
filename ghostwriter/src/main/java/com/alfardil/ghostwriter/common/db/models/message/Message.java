package com.alfardil.ghostwriter.common.db.models.message;

import com.alfardil.ghostwriter.common.db.helper.annotations.NotNullColumn;
import java.time.OffsetDateTime;
import lombok.Builder;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.Setter;
import lombok.ToString;

@Getter
@Setter
@Builder
@ToString
@EqualsAndHashCode
public class Message {

  @NotNullColumn
  private String id;

  @NotNullColumn
  private String telegramId;

  @NotNullColumn
  private String userMessage;

  @NotNullColumn
  private String aiResponse;

  @NotNullColumn
  private OffsetDateTime createdAt;
}
