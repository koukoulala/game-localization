document.addEventListener('alpine:init', () => {
    Alpine.data('translationApp', () => ({
        // --- State ---
        theme: localStorage.getItem('theme') || 'light',
        apiUrl: localStorage.getItem('apiUrl') || 'http://localhost:8051', // Default API URL, load from storage
        inputData: {
            original_content: '',
            config: {
                source_lang: localStorage.getItem('source_lang') || 'english',
                target_lang: localStorage.getItem('target_lang') || 'arabic',
                provider: localStorage.getItem('provider') || '',
                model: localStorage.getItem('model') || '',
                target_language_accent: localStorage.getItem('target_accent') || 'professional',
            },
        },
        availableProviders: {}, // Structure: { openai: ['gpt-4', ...], ollama: [...] }
        modelFilter: '',
        availableModels: [],
        status: { // Holds the latest state received from the stream
            current_step: null,
            progress_percent: 0,
            logs: [],
            chunks: null, // Will store original chunks
            contextualized_glossary: null,
            translated_chunks: null, // Will store translated chunks
            parallel_worker_results: null,
            critiques: null,
            final_document: null,
            error_info: null,
            metrics: null,
        },
        jobId: null,
        isLoading: false,
        eventSource: null, // Holds the SSE connection object
        logs: [], // Real-time logs from SSE
        translatedChunks: [], // Real-time translated chunks
        activeTab: 'full', // 'full', 'chunks', 'logs'
        translationStartTime: null,
        translationDuration: '00h:00m:00s',


        // --- Utility Functions (defined within the component) ---
        cleanMarkdown(text) {
            if (typeof text !== 'string') {
                if (text === undefined || text === null) return '';
                text = String(text);
            }
            // Basic cleaning, similar to Streamlit app
            let cleaned = text;
            cleaned = cleaned.replace(/```markdown\n?/g, ''); // Remove ```markdown tags
            cleaned = cleaned.replace(/\n?```/g, ''); // Remove closing ```
            cleaned = cleaned.replace(/\\n/g, '\n').replace(/\\t/g, '\t'); // Unescape newlines/tabs
            return cleaned;
        },
        isRtl(lang) {
            if (!lang) return false;
            return ["arabic", "hebrew", "farsi", "persian", "ar", "he", "fa"].includes(lang.toLowerCase());
        },
        countWords(text) {
            if (!text) return 0;
            return text.trim().split(/\s+/).filter(Boolean).length;
        },

        // --- Computed Properties ---
        get cleanedOriginalContent() {
            return this.cleanMarkdown(this.inputData.original_content);
        },
        get cleanedTranslatedContent() {
            return this.cleanMarkdown(this.status.final_document);
        },
        canStartTranslation() {
            return this.inputData.original_content.trim() !== '' &&
                   this.inputData.config.source_lang.trim() !== '' &&
                   this.inputData.config.target_lang.trim() !== '' &&
                   this.inputData.config.provider &&
                   this.inputData.config.model &&
                   this.apiUrl.trim() !== '';
        },

        // --- Methods ---
        init() {
            console.log('Alpine app initialized');
            this.fetchProviders();

            // Watch for theme changes
            this.$watch('theme', (newTheme) => {
                localStorage.setItem('theme', newTheme);
                console.log(`Theme changed to: ${newTheme}`);
            });

            // Watch for config changes to save them
            this.$watch('apiUrl', (newUrl) => localStorage.setItem('apiUrl', newUrl));
            this.$watch('inputData.config.source_lang', (val) => localStorage.setItem('source_lang', val));
            this.$watch('inputData.config.target_lang', (val) => localStorage.setItem('target_lang', val));
            this.$watch('inputData.config.provider', (val) => { localStorage.setItem('provider', val); this.inputData.config.model = ''; localStorage.removeItem('model'); }); // Reset model on provider change
            this.$watch('inputData.config.model', (val) => localStorage.setItem('model', val));
            this.$watch('inputData.config.target_language_accent', (val) => localStorage.setItem('target_accent', val));

            // Set initial model list if provider/models are loaded from localStorage
             this.updateModels();
        },

        async fetchProviders() {
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/providers`);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                // Accept both array of {provider, models} and array of {name, models}
                const providerDict = {};
                (data || []).forEach(item => {
                    const key = item.provider || item.name;
                    if (key && item.models) {
                        providerDict[key] = item.models;
                    }
                });
                this.availableProviders = providerDict;
                // If no provider is selected, select the first one
                if (!this.inputData.config.provider && Object.keys(providerDict).length > 0) {
                    this.inputData.config.provider = Object.keys(providerDict)[0];
                }
                console.log('Available providers fetched (raw data):', data);
                console.log('Available providers processed (dict):', this.availableProviders);
                this.updateModels(); // Update models based on fetched data and current provider
            } catch (error) {
                console.error("Error fetching providers:", error);
                this.availableProviders = {}; // Reset on error
                // TODO: Show user-friendly error
            }
        },

        updateModels() {
            const modelsForProvider = this.availableProviders[this.inputData.config.provider] || [];
            if (this.modelFilter) {
                this.availableModels = modelsForProvider.filter(m => m.toLowerCase().includes(this.modelFilter.toLowerCase()));
            } else {
                this.availableModels = modelsForProvider;
            }
             // Check if the currently selected model is still valid
            if (!this.availableModels.includes(this.inputData.config.model)) {
                 this.inputData.config.model = ''; // Reset if not valid
                 localStorage.removeItem('model');
            }
            console.log('Updating models for provider:', this.inputData.config.provider);
            console.log('Raw models for provider:', modelsForProvider);
            console.log('Filtered models:', this.availableModels);
        },

        handleFileUpload(event) {
            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.inputData.original_content = e.target.result;
                };
                reader.onerror = (e) => {
                    console.error("Error reading file:", e);
                    alert("Error reading file.");
                };
                reader.readAsText(file);
            }
        },

        generateUUID() { // Basic UUID generator
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        },

        calculateDuration() {
            if (!this.translationStartTime) return '00h:00m:00s';
            const endTime = Date.now();
            const durationSeconds = Math.round((endTime - this.translationStartTime) / 1000);
            const hours = Math.floor(durationSeconds / 3600);
            const minutes = Math.floor((durationSeconds % 3600) / 60);
            const seconds = durationSeconds % 60;
            this.translationDuration = `${String(hours).padStart(2, '0')}h:${String(minutes).padStart(2, '0')}m:${String(seconds).padStart(2, '0')}s`;
        },

        startTranslation() {
            if (!this.canStartTranslation()) {
                console.warn('Translation cannot start, required fields missing.');
                alert('Please fill in all required fields (API URL, Languages, Provider, Model) and provide input text.');
                return;
            }

            if (this.eventSource) {
                this.eventSource.close(); // Close previous connection if any
            }

            this.isLoading = true;
            this.jobId = this.generateUUID();
            this.translationStartTime = Date.now();
            this.translationDuration = 'Calculating...';
            this.activeTab = 'logs'; // Default to logs view on new translation
            // Reset status from previous runs
            this.status = {
                current_step: 'Initializing...', progress_percent: 0, logs: [], chunks: null, translated_chunks: null, final_document: null, error_info: null, critiques: null, metrics: null
            };

            const requestBody = {
                input: {
                    ...this.inputData,
                    job_id: this.jobId,
                    // Ensure only necessary fields are sent, reset others
                    original_content: this.inputData.original_content, // Send the content
                    config: this.inputData.config,
                    current_step: null, progress_percent: null, logs: [], chunks: null, contextualized_glossary: null,
                    translated_chunks: null, parallel_worker_results: null, critiques: null, final_document: null,
                    error_info: null, metrics: null,
                },
                config: {
                    configurable: { thread_id: this.jobId }
                }
            };

            console.log('Starting translation with Job ID:', this.jobId);
            console.log('Request Body:', JSON.stringify(requestBody, null, 2));

            // Construct URL for EventSource (GET request with body in query param)
            const streamUrl = `${this.apiUrl.replace(/\/$/, '')}/translate_graph/stream`;
            const params = new URLSearchParams();
            params.append('input', JSON.stringify(requestBody.input)); // Langserve expects 'input' and 'config' at top level for stream_log query
            params.append('config', JSON.stringify(requestBody.config));

            // Use EventSource for Server-Sent Events
            // Note: EventSource uses GET. We need to encode the body into the URL.
            // This might hit URL length limits for very large inputs. Consider alternative if needed.
            // A common pattern is POST to start, then GET stream with job_id. Langserve's stream_log might handle this GET pattern.
            this.sseEnded = false;
            this.eventSource = new EventSource(`${streamUrl}?${params.toString()}`);

            this.eventSource.onmessage = (event) => {
                console.log("SSE message received:", event.data);
                let eventData = null; // Define outside try block
                try {
                    eventData = JSON.parse(event.data);

                    // Expect eventData to have { output: {...}, metadata: {...} }
                    if (
                        typeof eventData === 'object' &&
                        eventData !== null &&
                        eventData.output &&
                        eventData.output.job_id === this.jobId
                    ) {
                        const newLogs = eventData.output.logs || [];
                        const existingLogs = this.status.logs || [];
                        this.status = {
                            ...this.status,
                            ...eventData.output,
                            logs: [...existingLogs, ...newLogs.slice(existingLogs.length)]
                        };
                        this.metadata = eventData.metadata || {};
                        console.log("Updated status:", this.status);
                        console.log("Updated metadata:", this.metadata);
                    } else {
                        console.log("Received non-state SSE message:", eventData);
                    }

                } catch (e) {
                    console.error("Error parsing SSE message:", e, "Data:", event.data);
                    // eventData remains null if parsing failed
                }

                // Check for final state markers AFTER processing the message
                // Ensure eventData is not null before accessing properties
                if (
                    eventData &&
                    eventData.output &&
                    (eventData.output.final_document || eventData.output.error_info) ||
                    this.status.final_document ||
                    this.status.error_info
                ) {
                    console.log("Final state detected in SSE message or status.");
                    console.log("Received eventData:", JSON.stringify(eventData, null, 2));
                    console.log("Status AFTER update:", JSON.stringify(this.status, null, 2));
                    this.isLoading = false;
                    this.calculateDuration();
                    // Don't close immediately, let the 'end' event handle it
                    // if (this.eventSource) {
                    //     this.eventSource.close();
                    //     this.eventSource = null;
                    // }
                    if (this.status.final_document && !this.status.translated_chunks && this.status.parallel_worker_results) {
                        this.status.translated_chunks = this.status.parallel_worker_results.map(r => r.refined_text || r.initial_translation || '');
                    }
                }
            };

            this.eventSource.addEventListener("log", (event) => {
                try {
                    const logObj = JSON.parse(event.data);
                    if (logObj && logObj.log) {
                        this.logs.push(logObj.log);
                    }
                } catch (e) {
                    console.error("Error parsing log SSE event:", e, event.data);
                }
            });

            // Real-time update of translated chunks
            this.$watch('status.translated_chunks', (newChunks) => {
                if (Array.isArray(newChunks)) {
                    this.translatedChunks = newChunks;
                }
            });

            this.eventSource.addEventListener("end", (event) => {
                console.log("SSE end event received.");
                this.sseEnded = true;
                if (this.eventSource) {
                    this.eventSource.close();
                    this.eventSource = null;
                }
            });

            this.eventSource.onerror = (error) => {
                if (this.sseEnded) {
                    console.log("SSE connection closed normally (end event).");
                    return;
                }
                console.error("EventSource failed:", error);
                this.isLoading = false;
                this.status.error_info = this.status.error_info || "Connection error or stream closed unexpectedly.";
                this.calculateDuration();
                if (this.eventSource) {
                    this.eventSource.close();
                    this.eventSource = null;
                }
            };
        },

        downloadFile(content, filename, contentType) {
            const blob = new Blob([content], { type: contentType });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

    }));
});