package com.apismith.tiktok;

import com.fasterxml.jackson.databind.JsonNode;

public final class TranscriptResult {
    private TranscriptResult() {}

    public static String failure(JsonNode run, JsonNode items) {
        String status = run.path("status").asText("");
        if (!"SUCCEEDED".equals(status)) return "Actor Run failed with status " + status + ".";
        String datasetId = run.path("defaultDatasetId").asText("");
        if (datasetId.isBlank()) return "Run succeeded without a default Dataset ID.";
        if (items == null || !items.isArray() || items.isEmpty()) return "Run succeeded but Dataset is empty.";
        boolean hasText = false;
        for (JsonNode item : items) {
            String err = item.path("errMsg").asText("");
            if (!err.isBlank()) return "Transcript failed: Actor returned errMsg.";
            if (!item.path("text").asText("").isBlank()) hasText = true;
        }
        return hasText ? null : "Run completed but transcript text is empty or missing.";
    }
}
