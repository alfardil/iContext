FROM eclipse-temurin:25-jdk AS builder
WORKDIR /build
COPY mvnw pom.xml ./
COPY .mvn/ .mvn/
RUN ./mvnw dependency:go-offline -q
COPY src/ src/
RUN ./mvnw package -DskipTests -q

FROM eclipse-temurin:25-jre
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/target/ghostwriter-0.0.1-SNAPSHOT.jar app.jar
COPY certs/ certs/
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
