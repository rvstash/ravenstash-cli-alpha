package com.ravenstash.demo;

import org.apache.commons.lang3.StringUtils;

import java.util.Map;

/** Simple formatter — used by test suite to verify utils work. */
public class Greeter {

    public static String greet(String name) {
        return "Hello, " + StringUtils.capitalize(name) + "!";
    }

    public static String formatPair(String key, String value) {
        return String.format("  %-20s %s", key, value);
    }

    public static String table(Map<String, String> pairs) {
        StringBuilder sb = new StringBuilder();
        pairs.forEach((k, v) -> sb.append(formatPair(k, v)).append("\n"));
        return sb.toString();
    }
}
