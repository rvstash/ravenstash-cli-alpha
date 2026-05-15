package com.ravenstash.demo;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * Fetches package metadata from Maven Central REST API.
 *
 * <pre>
 *   java -jar target/rvn-demo-java-0.1.0.jar info com.fasterxml.jackson.core:jackson-databind
 *   java -jar target/rvn-demo-java-0.1.0.jar versions org.slf4j:slf4j-api
 * </pre>
 */
public class Main {

    private static final Logger log = LoggerFactory.getLogger(Main.class);
    private static final String SEARCH_URL = "https://search.maven.org/solrsearch/select";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.out.println("Usage:");
            System.out.println("  rvn-demo-java info    <groupId:artifactId>");
            System.out.println("  rvn-demo-java versions <groupId:artifactId> [--limit N]");
            return;
        }

        String cmd = args[0];
        String coords = args[1];
        int limit = 10;
        for (int i = 2; i < args.length - 1; i++) {
            if ("--limit".equals(args[i])) {
                limit = Integer.parseInt(args[i + 1]);
            }
        }

        if (!coords.contains(":")) {
            System.err.println("Error: expected groupId:artifactId, got: " + coords);
            System.exit(1);
        }
        String[] parts = coords.split(":", 2);
        String g = parts[0];
        String a = parts[1];

        switch (cmd) {
            case "info" -> printInfo(g, a);
            case "versions" -> printVersions(g, a, limit);
            default -> {
                System.err.println("Unknown command: " + cmd);
                System.exit(1);
            }
        }
    }

    static void printInfo(String groupId, String artifactId) throws Exception {
        String url = SEARCH_URL + "?q=g:%22" + groupId + "%22+AND+a:%22" + artifactId
                + "%22&core=gav&rows=1&wt=json";
        JsonNode root = fetch(url);
        JsonNode docs = root.path("response").path("docs");
        if (docs.isEmpty()) {
            System.err.println("Not found: " + groupId + ":" + artifactId);
            System.exit(1);
        }
        JsonNode doc = docs.get(0);
        System.out.println();
        System.out.printf("  %-16s %s%n", "Group",      doc.path("g").asText("?"));
        System.out.printf("  %-16s %s%n", "Artifact",   doc.path("a").asText("?"));
        System.out.printf("  %-16s %s%n", "Latest",     doc.path("latestVersion").asText("?"));
        System.out.printf("  %-16s %s%n", "Packaging",  doc.path("p").asText("?"));
        System.out.printf("  %-16s %s%n", "Updated",    doc.path("timestamp").asText("?"));
        System.out.printf("  %-16s %s%n", "Versions",   doc.path("versionCount").asInt(0));
        System.out.println();
    }

    static void printVersions(String groupId, String artifactId, int limit) throws Exception {
        String url = SEARCH_URL + "?q=g:%22" + groupId + "%22+AND+a:%22" + artifactId
                + "%22&core=gav&rows=" + limit + "&wt=json&sort=version+desc";
        JsonNode root = fetch(url);
        JsonNode docs = root.path("response").path("docs");
        System.out.println("\n  " + groupId + ":" + artifactId + " — " + docs.size() + " versions");
        System.out.println("  " + StringUtils.repeat("─", 50));
        docs.forEach(d -> System.out.println("    " + d.path("v").asText("?")));
        System.out.println();
    }

    private static JsonNode fetch(String url) throws Exception {
        log.debug("GET {}", url);
        HttpClient client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("User-Agent", "rvn-demo-java/0.1.0")
                .GET()
                .build();
        HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new RuntimeException("HTTP " + resp.statusCode() + " from " + url);
        }
        return MAPPER.readTree(resp.body());
    }
}
