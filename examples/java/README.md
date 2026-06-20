# rvn-demo-java

Minimal Maven project for testing the alpha `rvn` package repository commands.

## Local Work

```bash
cd examples/java
rvn runtime use java 21
mvn test
mvn package
java -jar target/rvn-demo-java-0.1.0.jar info com.fasterxml.jackson.core:jackson-databind
```

Maven itself is not managed by `rvn runtime` in the current alpha. Install it
system-wide or through your preferred local toolchain manager.

## Ravenstash Package Repository

```bash
rvn auth login
rvn pkg repo create my-java-packages --kind maven --default
rvn pkg maven repo-url
rvn pkg maven settings
rvn pkg maven deploy target/rvn-demo-java-0.1.0.jar \
  --group com.ravenstash.demo \
  --artifact rvn-demo-java \
  --version 0.1.0
rvn pkg package list --repo <repository-id>
```

To fetch from a private Ravenstash Maven repository:

```bash
rvn pkg maven install com.ravenstash.demo:rvn-demo-java:0.1.0 --repo <repository-id>
```
