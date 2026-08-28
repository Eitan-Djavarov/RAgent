using System.Net;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Moq;
using Moq.Protected;
using TechDocIntelligence.Backend.Clients;
using TechDocIntelligence.Backend.Data;
using TechDocIntelligence.Backend.Models.DTOs;
using TechDocIntelligence.Backend.Services;

namespace TechDocIntelligence.Backend.Tests;

public sealed class AiResponseMapperTests
{
    [Fact]
    public void BuildFilterMetadata_IncludesSystemAndSeverityHints()
    {
        var query = new AskIncidentQueryDto
        {
            QueryText = "Why did radar tracking degrade?",
            SystemName = "Radar-APG",
            MinSeverity = "High",
            TopK = 3,
        };

        var filters = AiResponseMapper.BuildFilterMetadata(query);

        Assert.Equal("incident", filters["type"]);
        Assert.Equal("Radar-APG", filters["systemName"]);
        Assert.Equal("High", filters["severity"]);
    }

    [Fact]
    public void MapStructuredResponse_MapsAnalysisFieldsAndCitations()
    {
        var raw = new AiQueryResponseDto(
            Answer: "## Executive Summary\nFallback text",
            Sources:
            [
                new AiSourceCitationDto("doc-1", "chunk-a", 0.91),
            ],
            LatencyMs: 42.5,
            Analysis: new AiStructuredAnalysisDto(
                ExecutiveSummary: "Radar track processor memory growth caused resets.",
                RootCauseAnalysis: "Scratch arena leak under dense TWS load.",
                RecommendedMitigations: "Disable debug ring; add RSS governor.",
                SourceCitations:
                [
                    new AiSourceCitationDto(
                        "doc-1",
                        "scratch arena high water 5.9GB",
                        0.93,
                        CitationIndex: 1,
                        DocId: "doc-1",
                        System: "Radar-APG",
                        Severity: "High"),
                ]),
            RetrievalMode: "hybrid+rerank",
            ToolUsed: "HYBRID_RAG");

        var mapped = AiResponseMapper.MapStructuredResponse(raw);

        Assert.Equal("Radar track processor memory growth caused resets.", mapped.Summary);
        Assert.Equal("Scratch arena leak under dense TWS load.", mapped.RootCause);
        Assert.Equal("Disable debug ring; add RSS governor.", mapped.ActionItems);
        Assert.Equal(42.5, mapped.LatencyMs);
        Assert.Equal("hybrid+rerank", mapped.RetrievalMode);
        Assert.Equal("HYBRID_RAG", mapped.ToolUsed);
        Assert.False(mapped.Cached);
        Assert.Null(mapped.SqlQueryResult);
        Assert.Single(mapped.Citations);
        Assert.Equal("doc-1", mapped.Citations[0].DocumentId);
        Assert.Equal(1, mapped.Citations[0].CitationIndex);
        Assert.Equal("doc-1", mapped.Citations[0].DocId);
        Assert.Equal("High", mapped.Citations[0].Severity);
        Assert.Equal("Radar-APG", mapped.Citations[0].System);
    }

    [Fact]
    public void MapStructuredResponse_PropagatesCachedFlag()
    {
        var raw = new AiQueryResponseDto(
            Answer: "cached answer",
            Sources: [],
            LatencyMs: 3.2,
            Analysis: new AiStructuredAnalysisDto(
                ExecutiveSummary: "Cached summary",
                RootCauseAnalysis: "Cached root cause",
                RecommendedMitigations: "Cached actions",
                SourceCitations: []),
            RetrievalMode: "hybrid+rerank",
            ToolUsed: "HYBRID_RAG",
            Cached: true);

        var mapped = AiResponseMapper.MapStructuredResponse(raw);

        Assert.True(mapped.Cached);
        Assert.Equal(3.2, mapped.LatencyMs);
        Assert.Equal("Cached summary", mapped.Summary);
    }

    [Fact]
    public void ToAiQueryRequest_ForwardsSessionId()
    {
        var query = new AskIncidentQueryDto
        {
            QueryText = "What about mitigations?",
            TopK = 3,
            SessionId = "sess-123",
        };

        var payload = AiResponseMapper.ToAiQueryRequest(query);

        Assert.Equal("sess-123", payload.SessionId);
        Assert.Equal("What about mitigations?", payload.Query);
    }

    [Fact]
    public void MapStructuredResponse_PropagatesRewrittenQuery()
    {
        var raw = new AiQueryResponseDto(
            Answer: "answer",
            Sources: [],
            LatencyMs: 11,
            Analysis: new AiStructuredAnalysisDto(
                ExecutiveSummary: "Summary",
                RootCauseAnalysis: "Cause",
                RecommendedMitigations: "Actions",
                SourceCitations: []),
            RetrievalMode: "hybrid+rerank",
            ToolUsed: "HYBRID_RAG",
            SessionId: "sess-9",
            OriginalQuery: "what about it?",
            RewrittenQuery: "What caused AESA buffer overflow mitigations?");

        var mapped = AiResponseMapper.MapStructuredResponse(raw);

        Assert.Equal("sess-9", mapped.SessionId);
        Assert.Equal("what about it?", mapped.OriginalQuery);
        Assert.Equal("What caused AESA buffer overflow mitigations?", mapped.RewrittenQuery);
    }

    [Fact]
    public void MapStructuredResponse_ParsesMarkdownWhenAnalysisMissing()
    {
        var answer = """
            ## Executive Summary
            UAV C2 dropped under jamming.

            ## Root Cause Analysis
            SINR collapse from barrage jamming.

            ## Recommended Mitigation / Corrective Actions
            Enable PROFILE_AJ_B hop profile.

            ## Source Citations
            - document_id=abc
            """;

        var raw = new AiQueryResponseDto(
            Answer: answer,
            Sources: [new AiSourceCitationDto("abc", "SINR=-4.0dB", 0.88)],
            LatencyMs: 12,
            Analysis: null,
            RetrievalMode: "hybrid");

        var mapped = AiResponseMapper.MapStructuredResponse(raw);

        Assert.Contains("UAV C2", mapped.Summary, StringComparison.Ordinal);
        Assert.Contains("barrage jamming", mapped.RootCause, StringComparison.Ordinal);
        Assert.Contains("PROFILE_AJ_B", mapped.ActionItems, StringComparison.Ordinal);
        Assert.Single(mapped.Citations);
    }
}

public sealed class AiServiceClientMappingTests
{
    [Fact]
    public async Task QueryIncidentsAsync_SendsFiltersAndMapsStructuredPayload()
    {
        var responseJson = """
            {
              "answer": "## Executive Summary\nSummary body",
              "sources": [
                { "documentId": "11111111-1111-1111-1111-111111111111", "chunkText": "telemetry drop", "score": 0.81 }
              ],
              "latencyMs": 33.2,
              "retrievalMode": "hybrid+rerank",
              "toolUsed": "HYBRID_COMBINED",
              "summary": "C2 link degraded in contested RF.",
              "rootCause": "Adaptive barrage jamming and antenna lag.",
              "actionItems": "Enable AJ hop profile and tighten pointing.",
              "sqlQueryResult": {
                "query": "SELECT COUNT(*)::int AS incident_count FROM incidents WHERE severity = 'Critical'",
                "rowCount": 1,
                "columns": ["incident_count"],
                "rows": [{ "incident_count": 2 }],
                "interpretation": "Metric query returned incident_count=2."
              },
              "analysis": {
                "executiveSummary": "C2 link degraded in contested RF.",
                "rootCauseAnalysis": "Adaptive barrage jamming and antenna lag.",
                "recommendedMitigations": "Enable AJ hop profile and tighten pointing.",
                "sourceCitations": [
                  { "documentId": "11111111-1111-1111-1111-111111111111", "chunkText": "SINR collapse", "score": 0.91 }
                ]
              }
            }
            """;

        string? capturedBody = null;
        var handler = new Mock<HttpMessageHandler>(MockBehavior.Strict);
        handler.Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Returns(async (HttpRequestMessage request, CancellationToken _) =>
            {
                Assert.Equal(HttpMethod.Post, request.Method);
                Assert.Equal("/api/v1/query", request.RequestUri?.AbsolutePath);
                capturedBody = request.Content is null
                    ? null
                    : await request.Content.ReadAsStringAsync();
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(responseJson, Encoding.UTF8, "application/json"),
                };
            });

        var httpClient = new HttpClient(handler.Object)
        {
            BaseAddress = new Uri("http://ai-service/"),
        };

        var client = new AiServiceClient(
            httpClient,
            Options.Create(new AiServiceOptions { BaseUrl = "http://ai-service", TimeoutSeconds = 30, RetryCount = 0 }),
            NullLogger<AiServiceClient>.Instance);

        var result = await client.QueryIncidentsAsync(new AskIncidentQueryDto
        {
            QueryText = "Explain UAV telemetry drops",
            SystemName = "UAV-Link-X",
            MinSeverity = "High",
            TopK = 3,
        });

        Assert.NotNull(capturedBody);
        using var payload = JsonDocument.Parse(capturedBody);
        Assert.Equal("Explain UAV telemetry drops", payload.RootElement.GetProperty("query").GetString());
        Assert.Equal(3, payload.RootElement.GetProperty("topK").GetInt32());
        Assert.True(payload.RootElement.GetProperty("structured").GetBoolean());
        var filters = payload.RootElement.GetProperty("filterMetadata");
        Assert.Equal("incident", filters.GetProperty("type").GetString());
        Assert.Equal("UAV-Link-X", filters.GetProperty("systemName").GetString());
        Assert.Equal("High", filters.GetProperty("severity").GetString());

        Assert.Equal("C2 link degraded in contested RF.", result.Summary);
        Assert.Equal("Adaptive barrage jamming and antenna lag.", result.RootCause);
        Assert.Equal("Enable AJ hop profile and tighten pointing.", result.ActionItems);
        Assert.Equal(33.2, result.LatencyMs);
        Assert.Equal("HYBRID_COMBINED", result.ToolUsed);
        Assert.NotNull(result.SqlQueryResult);
        Assert.Equal(1, result.SqlQueryResult!.RowCount);
        Assert.Contains("incident_count", result.SqlQueryResult.Query, StringComparison.Ordinal);
        Assert.Single(result.Citations);
        Assert.Equal(0.91, result.Citations[0].Score);
    }
}

public sealed class IncidentServiceAnalyzeTests
{
    [Fact]
    public async Task AnalyzeIncidentAsync_AppliesMinSeverityFilterAgainstPostgres()
    {
        var highId = Guid.Parse("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
        var lowId = Guid.Parse("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb");

        var options = new DbContextOptionsBuilder<AppDbContext>()
            .UseInMemoryDatabase($"incidents-{Guid.NewGuid():N}")
            .Options;

        await using var db = new AppDbContext(options);
        db.Incidents.AddRange(
            new IncidentEntity
            {
                Id = highId,
                Title = "High sev",
                Description = "high",
                SystemName = "Radar-APG",
                Severity = IncidentSeverity.High,
                CreatedAt = DateTimeOffset.UtcNow,
            },
            new IncidentEntity
            {
                Id = lowId,
                Title = "Low sev",
                Description = "low",
                SystemName = "Radar-APG",
                Severity = IncidentSeverity.Low,
                CreatedAt = DateTimeOffset.UtcNow,
            });
        await db.SaveChangesAsync();

        var ai = new Mock<IAiServiceClient>(MockBehavior.Strict);
        ai.Setup(client => client.QueryIncidentsAsync(
                It.IsAny<AskIncidentQueryDto>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(new AskIncidentResponseDto(
                Summary: "summary",
                RootCause: "root",
                ActionItems: "actions",
                Citations:
                [
                    new IncidentCitationDto(highId.ToString("D"), "high chunk", 0.9),
                    new IncidentCitationDto(lowId.ToString("D"), "low chunk", 0.8),
                ],
                LatencyMs: 10,
                ToolUsed: "HYBRID_RAG"));

        var service = new IncidentService(db, ai.Object, NullLogger<IncidentService>.Instance);
        var result = await service.AnalyzeIncidentAsync(new AskIncidentQueryDto
        {
            QueryText = "radar memory",
            MinSeverity = "Medium",
            TopK = 4,
        });

        Assert.Single(result.Citations);
        Assert.Equal(highId.ToString("D"), result.Citations[0].DocumentId);
        ai.VerifyAll();
    }
}
