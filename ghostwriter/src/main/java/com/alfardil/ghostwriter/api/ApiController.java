package com.alfardil.ghostwriter.api;

import com.alfardil.ghostwriter.common.db.models.telegram.TelegramUpdate;
import com.alfardil.ghostwriter.common.service.intake.MessageIntake;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class ApiController {

  private static final Logger log = LoggerFactory.getLogger(ApiController.class);

  private final MessageIntake messageIntake;

  public ApiController(MessageIntake messageIntake) {
    this.messageIntake = messageIntake;
  }

  @PostMapping("/webhook")
  public ResponseEntity<Void> handleTelegramWebhook(
    @RequestBody TelegramUpdate update
  ) {
    if (update.getMessage() == null || update.getMessage().getText() == null) {
      return ResponseEntity.ok().build();
    }

    String userId = String.valueOf(update.getMessage().getFrom().getId());
    String text = update.getMessage().getText();

    log.info(
      "WEBHOOK HIT | updateId={} | userId={} | text='{}'",
      update.getUpdateId(),
      userId,
      text
    );

    messageIntake.accept(userId, text);

    return ResponseEntity.ok().build();
  }
}
