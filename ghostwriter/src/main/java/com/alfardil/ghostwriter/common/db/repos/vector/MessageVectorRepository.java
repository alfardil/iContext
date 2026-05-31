package com.alfardil.ghostwriter.common.db.repos.vector;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

/**
 * Read access to the cloud {@code MessageVector} replica that the Mac publishes into
 * (see DEPLOYMENT.md). Used only by the {@code prod} profile, where ghostwriter answers
 * message questions with a pgvector KNN instead of calling the Mac's MCP server.
 */
public interface MessageVectorRepository {

  /** One semantic hit from the {@code MessageVector} table. */
  record MessageHit(
    String sentAt,
    String sender,
    String senderName,
    boolean isFromMe,
    String chatGuid,
    String text,
    double score
  ) {}

  /**
   * Cosine-KNN over the message embeddings, newest-similar first.
   *
   * @param embedding  the query vector (384-dim, MiniLM-L6 — same model the Mac used)
   * @param senderName optional case-insensitive substring filter on the contact name
   * @param since      optional lower bound on send time (inclusive)
   * @param until      optional upper bound on send time (exclusive)
   * @param limit      max hits to return
   */
  List<MessageHit> search(
    float[] embedding,
    String senderName,
    OffsetDateTime since,
    OffsetDateTime until,
    int limit
  );

  /** Newest message timestamp present in the replica, i.e. how fresh the last Mac sync was. */
  Optional<OffsetDateTime> latestSyncedAt();
}
