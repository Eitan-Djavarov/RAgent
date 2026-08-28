using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.Extensions.Options;
using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Clients;

public sealed class AiServiceClient : IAiServiceClient
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _httpClient;
    private readonly AiServiceOptions _options;
    private readonly ILogger<AiServiceClient> _logger;

    public AiServiceClient(
        HttpClient httpClient,
        IOptions<AiServiceOptions> options,
        ILogger<AiServiceClient> logger)
    {
        _httpClient = httpClient;
        _options = options.Value;
        _logger = logger;
    }

    public Task<AiIngestResponseDto> IngestAsync(
        AiIngestRequestDto request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<AiIngestRequestDto, AiIngestResponseDto>(
            HttpMethod.Post,
            "api/v1/ingest",
            request,
            "ingest",
            cancellationToken);
    }

    public async Task<FileIngestResponseDto> IngestFileAsync(
        Stream fileStream,
        string fileName,
        string? contentType,
        string? title,
        string system,
        string severity,
        string? subsystemTags,
        CancellationToken cancellationToken = default)
    {
        await using var buffer = new MemoryStream();
        await fileStream.CopyToAsync(buffer, cancellationToken);
        var bytes = buffer.ToArray();

        return await SendMultipartAsync<FileIngestResponseDto>(
            "api/v1/ingest/file",
            "ingest-file",
            () =>
            {
                var content = new MultipartFormDataContent();
                var fileContent = new ByteArrayContent(bytes);
                fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(
                    string.IsNullOrWhiteSpace(contentType) ? "application/octet-stream" : contentType);
                content.Add(fileContent, "file", fileName);
                if (!string.IsNullOrWhiteSpace(title))
                {
                    content.Add(new StringContent(title), "title");
                }

                content.Add(new StringContent(system), "system");
                content.Add(new StringContent(severity), "severity");
                content.Add(new StringContent(subsystemTags ?? string.Empty), "subsystemTags");
                return content;
            },
            cancellationToken);
    }

    public Task<AiQueryResponseDto> QueryAsync(
        AiQueryRequestDto request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<AiQueryRequestDto, AiQueryResponseDto>(
            HttpMethod.Post,
            "api/v1/query",
            request,
            "query",
            cancellationToken);
    }

    public async Task<AskIncidentResponseDto> QueryIncidentsAsync(
        AskIncidentQueryDto request,
        CancellationToken cancellationToken = default)
    {
        var payload = AiResponseMapper.ToAiQueryRequest(request);
        _logger.LogInformation(
            "Querying AI service with topK={TopK}, filters={Filters}",
            payload.TopK,
            payload.FilterMetadata is null
                ? "{}"
                : string.Join(",", payload.FilterMetadata.Select(pair => $"{pair.Key}={pair.Value}")));

        var raw = await QueryAsync(payload, cancellationToken);
        return AiResponseMapper.MapStructuredResponse(raw);
    }

    public async Task<HttpResponseMessage> StreamQueryIncidentsAsync(
        AskIncidentQueryDto request,
        CancellationToken cancellationToken = default)
    {
        var payload = AiResponseMapper.ToAiQueryRequest(request);
        _logger.LogInformation(
            "Opening AI SSE stream topK={TopK} sessionId={SessionId}",
            payload.TopK,
            payload.SessionId ?? "(none)");

        using var requestMessage = new HttpRequestMessage(HttpMethod.Post, "api/v1/ask/stream")
        {
            Content = JsonContent.Create(payload, options: JsonOptions),
        };
        requestMessage.Headers.Accept.ParseAdd("text/event-stream");
        if (!string.IsNullOrWhiteSpace(payload.SessionId))
        {
            requestMessage.Headers.TryAddWithoutValidation("X-Session-Id", payload.SessionId);
        }

        var response = await _httpClient.SendAsync(
            requestMessage,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            var body = await response.Content.ReadAsStringAsync(cancellationToken);
            var headers = CaptureHeaders(response);
            var statusCode = response.StatusCode;
            response.Dispose();
            throw new AiServiceException(
                BuildErrorMessage("ask/stream", statusCode, body),
                statusCode,
                body,
                headers);
        }

        return response;
    }

    public Task<DocumentDeleteResponseDto> DeleteDocumentAsync(
        Guid documentId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<object?, DocumentDeleteResponseDto>(
            HttpMethod.Delete,
            $"api/v1/documents/{documentId:D}",
            null,
            "delete-document",
            cancellationToken);
    }

    public async Task<bool> IsHealthyAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await _httpClient.GetAsync("health", cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or OperationCanceledException)
        {
            _logger.LogWarning(ex, "AI service health check failed");
            return false;
        }
    }

    private async Task<TResponse> SendAsync<TRequest, TResponse>(
        HttpMethod method,
        string path,
        TRequest payload,
        string operationName,
        CancellationToken cancellationToken)
        where TResponse : class
    {
        return await SendWithRetriesAsync<TResponse>(
            operationName,
            async ct =>
            {
                using var requestMessage = new HttpRequestMessage(method, path);
                if (payload is not null)
                {
                    requestMessage.Content = JsonContent.Create(payload, options: JsonOptions);
                }

                if (payload is AiQueryRequestDto queryRequest
                    && !string.IsNullOrWhiteSpace(queryRequest.SessionId))
                {
                    requestMessage.Headers.TryAddWithoutValidation(
                        "X-Session-Id",
                        queryRequest.SessionId);
                }

                return await _httpClient.SendAsync(
                    requestMessage,
                    HttpCompletionOption.ResponseHeadersRead,
                    ct);
            },
            cancellationToken);
    }

    private async Task<TResponse> SendMultipartAsync<TResponse>(
        string path,
        string operationName,
        Func<HttpContent> contentFactory,
        CancellationToken cancellationToken)
        where TResponse : class
    {
        return await SendWithRetriesAsync<TResponse>(
            operationName,
            async ct =>
            {
                using var requestMessage = new HttpRequestMessage(HttpMethod.Post, path)
                {
                    Content = contentFactory(),
                };
                return await _httpClient.SendAsync(
                    requestMessage,
                    HttpCompletionOption.ResponseHeadersRead,
                    ct);
            },
            cancellationToken);
    }

    private async Task<TResponse> SendWithRetriesAsync<TResponse>(
        string operationName,
        Func<CancellationToken, Task<HttpResponseMessage>> send,
        CancellationToken cancellationToken)
        where TResponse : class
    {
        var attempt = 0;
        var maxAttempts = Math.Max(1, _options.RetryCount + 1);
        Exception? lastException = null;

        while (attempt < maxAttempts)
        {
            attempt++;
            try
            {
                using var response = await send(cancellationToken);
                var body = await response.Content.ReadAsStringAsync(cancellationToken);

                if (!response.IsSuccessStatusCode)
                {
                    _logger.LogError(
                        "AI {Operation} failed with status {StatusCode} (attempt {Attempt} of {MaxAttempts}): {Body}",
                        operationName,
                        (int)response.StatusCode,
                        attempt,
                        maxAttempts,
                        body);

                    // Never retry client security / rate-limit responses.
                    if (response.StatusCode is HttpStatusCode.BadRequest or HttpStatusCode.TooManyRequests)
                    {
                        throw new AiServiceException(
                            BuildErrorMessage(operationName, response.StatusCode, body),
                            response.StatusCode,
                            body,
                            CaptureHeaders(response));
                    }

                    if (IsTransient(response.StatusCode) && attempt < maxAttempts)
                    {
                        await Task.Delay(TimeSpan.FromMilliseconds(200 * attempt), cancellationToken);
                        continue;
                    }

                    throw new AiServiceException(
                        BuildErrorMessage(operationName, response.StatusCode, body),
                        response.StatusCode,
                        body,
                        CaptureHeaders(response));
                }

                var result = JsonSerializer.Deserialize<TResponse>(body, JsonOptions);
                if (result is null)
                {
                    throw new AiServiceException(
                        $"AI service {operationName} returned an empty or invalid response body.",
                        response.StatusCode,
                        body);
                }

                return result;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            catch (TaskCanceledException ex)
            {
                lastException = ex;
                _logger.LogWarning(
                    ex,
                    "AI {Operation} timed out after {TimeoutSeconds}s (attempt {Attempt} of {MaxAttempts})",
                    operationName,
                    _options.TimeoutSeconds,
                    attempt,
                    maxAttempts);

                if (attempt >= maxAttempts)
                {
                    throw new AiServiceException(
                        $"AI service {operationName} timed out after {_options.TimeoutSeconds} seconds.",
                        ex,
                        HttpStatusCode.RequestTimeout);
                }

                await Task.Delay(TimeSpan.FromMilliseconds(200 * attempt), cancellationToken);
            }
            catch (HttpRequestException ex)
            {
                lastException = ex;
                _logger.LogWarning(
                    ex,
                    "AI {Operation} transport error (attempt {Attempt} of {MaxAttempts})",
                    operationName,
                    attempt,
                    maxAttempts);

                if (attempt >= maxAttempts)
                {
                    throw new AiServiceException(
                        $"AI service {operationName} is unreachable.",
                        ex);
                }

                await Task.Delay(TimeSpan.FromMilliseconds(200 * attempt), cancellationToken);
            }
        }

        throw new AiServiceException(
            $"AI service {operationName} failed after {maxAttempts} attempts.",
            lastException ?? new InvalidOperationException("Unknown AI client failure."));
    }

    private static bool IsTransient(HttpStatusCode statusCode) =>
        statusCode is HttpStatusCode.RequestTimeout
            or HttpStatusCode.BadGateway
            or HttpStatusCode.ServiceUnavailable
            or HttpStatusCode.GatewayTimeout;

    private static IReadOnlyDictionary<string, string> CaptureHeaders(HttpResponseMessage response)
    {
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var header in response.Headers)
        {
            headers[header.Key] = string.Join(",", header.Value);
        }

        foreach (var header in response.Content.Headers)
        {
            headers[header.Key] = string.Join(",", header.Value);
        }

        return headers;
    }

    private static string BuildErrorMessage(string operationName, HttpStatusCode statusCode, string body)
    {
        var detail = TryExtractProblemDetail(body);
        if (!string.IsNullOrWhiteSpace(detail))
        {
            return detail;
        }

        return $"AI service {operationName} failed with status {(int)statusCode}.";
    }

    private static string? TryExtractProblemDetail(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(body);
            if (document.RootElement.TryGetProperty("detail", out var detail)
                && detail.ValueKind == JsonValueKind.String)
            {
                return detail.GetString();
            }

            if (document.RootElement.TryGetProperty("title", out var title)
                && title.ValueKind == JsonValueKind.String)
            {
                return title.GetString();
            }
        }
        catch (JsonException)
        {
            // fall through
        }

        return null;
    }
}
