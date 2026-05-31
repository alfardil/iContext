CREATE TABLE "QuestionCache" (
  id UUID PRIMARY KEY NOT NULL,
  "userId" VARCHAR(255) NOT NULL,
  "question" TEXT NOT NULL,
  "embedding" vector(384) NOT NULL,
  "aiResponse" TEXT NOT NULL,
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "expiresAt" TIMESTAMPTZ NOT NULL
);

CREATE INDEX "QuestionCache_embedding_idx"
  ON "QuestionCache" USING hnsw ("embedding" vector_cosine_ops);

CREATE INDEX "QuestionCache_userId_expiresAt_idx"
  ON "QuestionCache" ("userId", "expiresAt");
