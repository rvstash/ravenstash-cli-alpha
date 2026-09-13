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
rvs art repo create my-java-packages --ecosystem maven --default
rvs art endpoint --format maven
rvs art native config mvn
rvs art maven publish target/rvs-demo-java-0.1.0.jar \
  --group-id com.ravenstash.demo \
  --artifact-id rvs-demo-java \
  --version 0.1.0
rvs art package list --target <repo-name>
```

To fetch from a private Ravenstash Maven repository:

```bash
rvs art maven install com.ravenstash.demo:rvs-demo-java:0.1.0 --target <repo-name>
```
