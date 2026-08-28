using System.Text.RegularExpressions;
using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Clients;

public static class AiResponseMapper
{
    public static Dictionary<string, string?> BuildFilterMetadata(AskIncidentQueryDto request)
    {
        var filters = new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
        {
            ["type"] = "incident",
        };

        if (!string.IsNullOrWhiteSpace(request.SystemName))
        {
            filters["systemName"] = request.SystemName.Trim();
        }

        if (!string.IsNullOrWhiteSpace(request.MinSeverity)
            && TryParseSeverity(request.MinSeverity, out var severity))
        {
            filters["severity"] = severity.ToString();
        }

        return filters;
    }

    public static AiQueryRequestDto ToAiQueryRequest(AskIncidentQueryDto request)
    {
        var topK = request.TopK > 0 ? request.TopK : 4;
        return new AiQueryRequestDto(
            request.QueryText.Trim(),
            topK,
            BuildFilterMetadata(request),
            Structured: true,
            SessionId: string.IsNullOrWhiteSpace(request.SessionId)
                ? null
                : request.SessionId.Trim());
    }

    public static AskIncidentResponseDto MapStructuredResponse(AiQueryResponseDto response)
    {
        var citationSource = response.Citations
            ?? response.Analysis?.SourceCitations
            ?? response.Sources;

        var citations = citationSource
            .Select((source, index) => new IncidentCitationDto(
                DocumentId: source.DocumentId,
                ChunkText: source.ChunkText,
                Score: source.Score,
                CitationIndex: source.CitationIndex ?? (index + 1),
                DocId: source.DocId ?? source.DocumentId,
                System: source.System,
                Severity: source.Severity,
                ParentId: source.ParentId))
            .ToList();

        SqlQueryResultDto? sqlResult = null;
        if (response.SqlQueryResult is not null)
        {
            sqlResult = new SqlQueryResultDto(
                response.SqlQueryResult.Query,
                response.SqlQueryResult.RowCount,
                response.SqlQueryResult.Columns ?? Array.Empty<string>(),
                response.SqlQueryResult.Rows ?? Array.Empty<Dictionary<string, object?>>(),
                response.SqlQueryResult.Interpretation ?? string.Empty);
        }

        if (!string.IsNullOrWhiteSpace(response.Summary)
            || response.Analysis is not null)
        {
            var summary = !string.IsNullOrWhiteSpace(response.Summary)
                ? response.Summary!
                : response.Analysis!.ExecutiveSummary;
            var rootCause = !string.IsNullOrWhiteSpace(response.RootCause)
                ? response.RootCause!
                : response.Analysis?.RootCauseAnalysis
                    ?? "See answer body for root-cause details.";
            var actionItems = !string.IsNullOrWhiteSpace(response.ActionItems)
                ? response.ActionItems!
                : response.Analysis?.RecommendedMitigations
                    ?? "See answer body for recommended actions.";

            return new AskIncidentResponseDto(
                Summary: summary,
                RootCause: rootCause,
                ActionItems: actionItems,
                Citations: citations,
                LatencyMs: response.LatencyMs,
                ToolUsed: response.ToolUsed,
                SqlQueryResult: sqlResult,
                Answer: response.Answer,
                RetrievalMode: response.RetrievalMode,
                Cached: response.Cached,
                SessionId: response.SessionId,
                OriginalQuery: response.OriginalQuery,
                RewrittenQuery: response.RewrittenQuery,
                FaithfulnessScore: response.FaithfulnessScore,
                IsGrounded: response.IsGrounded,
                UnsupportedClaims: response.UnsupportedClaims);
        }

        var parsed = ParseMarkdownSections(response.Answer);
        return new AskIncidentResponseDto(
            Summary: parsed.Summary,
            RootCause: parsed.RootCause,
            ActionItems: parsed.ActionItems,
            Citations: citations,
            LatencyMs: response.LatencyMs,
            ToolUsed: response.ToolUsed,
            SqlQueryResult: sqlResult,
            Answer: response.Answer,
            RetrievalMode: response.RetrievalMode,
            Cached: response.Cached,
            SessionId: response.SessionId,
            OriginalQuery: response.OriginalQuery,
            RewrittenQuery: response.RewrittenQuery,
            FaithfulnessScore: response.FaithfulnessScore,
            IsGrounded: response.IsGrounded,
            UnsupportedClaims: response.UnsupportedClaims);
    }

    public static bool TryParseSeverity(string? value, out IncidentSeverity severity)
    {
        severity = IncidentSeverity.Low;
        if (string.IsNullOrWhiteSpace(value))
        {
            return false;
        }

        return Enum.TryParse(value.Trim(), ignoreCase: true, out severity);
    }

    private static (string Summary, string RootCause, string ActionItems) ParseMarkdownSections(string answer)
    {
        if (string.IsNullOrWhiteSpace(answer))
        {
            return ("No summary available.", "No root cause available.", "No action items available.");
        }

        var summary = ExtractSection(answer, "Executive Summary", "Root Cause Analysis");
        var rootCause = ExtractSection(answer, "Root Cause Analysis", "Recommended Mitigation");
        var actions = ExtractSection(answer, "Recommended Mitigation / Corrective Actions", "Source Citations");
        if (string.IsNullOrWhiteSpace(actions))
        {
            actions = ExtractSection(answer, "Recommended Mitigation", "Source Citations");
        }

        return (
            string.IsNullOrWhiteSpace(summary) ? answer.Trim() : summary,
            string.IsNullOrWhiteSpace(rootCause) ? "See answer body for root-cause details." : rootCause,
            string.IsNullOrWhiteSpace(actions) ? "See answer body for recommended actions." : actions);
    }

    private static string ExtractSection(string markdown, string startHeading, string endHeading)
    {
        var pattern = $@"##\s*{Regex.Escape(startHeading)}\s*(.*?)(?=##\s*{Regex.Escape(endHeading)}|$)";
        var match = Regex.Match(markdown, pattern, RegexOptions.IgnoreCase | RegexOptions.Singleline);
        return match.Success ? match.Groups[1].Value.Trim() : string.Empty;
    }
}
