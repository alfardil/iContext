-- Cloud replica of iMessage vectors, pushed by the Mac while it's awake (see DEPLOYMENT.md).
-- ghostwriter reads this table directly in the `prod` profile — the Mac is never in the
-- request path, so the bot answers from whatever was last synced even while the Mac sleeps.
-- Text is stored alongside the embedding so a read needs nothing from the Mac.
CREATE TABLE "MessageVector" (
  "msgGuid"    TEXT PRIMARY KEY,
  "chatGuid"   TEXT NOT NULL,
  "sentAt"     TIMESTAMPTZ NOT NULL,
  "sender"     TEXT,
  "senderName" TEXT,
  "isFromMe"   BOOLEAN NOT NULL,
  "text"       TEXT NOT NULL,
  "embedding"  vector(384) NOT NULL
);

CREATE INDEX "MessageVector_embedding_idx"
  ON "MessageVector" USING hnsw ("embedding" vector_cosine_ops);

CREATE INDEX "MessageVector_chatGuid_idx" ON "MessageVector" ("chatGuid");
CREATE INDEX "MessageVector_senderName_idx" ON "MessageVector" ("senderName");
CREATE INDEX "MessageVector_sentAt_idx" ON "MessageVector" ("sentAt");
