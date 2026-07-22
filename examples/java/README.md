# rvs-demo-java

Minimal Maven project for testing the alpha `rvs` package repository commands.

## Local Work

```bash
cd examples/java
rvs runtime use java 21
mvn test
mvn package
java -jar target/rvs-demo-java-0.1.0.jar info com.fasterxml.jackson.core:jackson-databind
```

Maven itself is not managed by `rvs runtime` in the current alpha. Install it
system-wide or through your preferred local toolchain manager.

## Ravenstash Package Repository

```bash
rvs auth login
rvs pkg repo create my-java-packages --kind maven --default
rvs pkg maven repo-url
rvs pkg maven settings
rvs pkg maven deploy target/rvs-demo-java-0.1.0.jar \
  --group com.ravenstash.demo \
  --artifact rvs-demo-java \
  --version 0.1.0
rvs pkg package list --repo <repository-id>
```

To fetch from a private Ravenstash Maven repository:

```bash
rvs pkg maven install com.ravenstash.demo:rvs-demo-java:0.1.0 --repo <repository-id>
```
