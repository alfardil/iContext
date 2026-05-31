package com.alfardil.ghostwriter.common.db.repos.message;

import com.alfardil.ghostwriter.common.db.models.message.Message;

public interface MessageRepository {
    void createMessage(Message message);

    Message getMessageById(String id);

    boolean updateMessage(Message message);

    boolean deleteMessageById(String id);
}
