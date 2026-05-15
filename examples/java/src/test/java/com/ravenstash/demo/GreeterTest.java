package com.ravenstash.demo;

import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.assertThat;

class GreeterTest {

    @Test
    void greetCapitalisesName() {
        assertThat(Greeter.greet("world")).isEqualTo("Hello, World!");
    }

    @Test
    void greetAlreadyCapitalised() {
        assertThat(Greeter.greet("Alice")).isEqualTo("Hello, Alice!");
    }

    @Test
    void formatPairPads() {
        String line = Greeter.formatPair("Group", "com.example");
        assertThat(line).startsWith("  Group");
        assertThat(line).contains("com.example");
    }
}
