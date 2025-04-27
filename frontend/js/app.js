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
                translation_mode: localStorage.getItem('translation_mode') || 'deep_mode',
            },
        },
        originalFilename: '', // Store the original filename
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
        
        // New properties for job history
        jobHistory: [],
        selectedJob: null,
        viewMode: 'home', // 'home', 'form', 'history', 'job-details', 'llm-config', 'env-config', 'glossary'
        
        // Statistics for home page
        jobStats: {
            totalJobs: 0,
            totalWords: 0,
            totalChars: 0,
            deepTranslationPercent: 0,
            topModels: [],
            topAccents: [],
            topLanguages: []
        },
        
        // LLM Configuration
        llmConfigs: [],
        defaultLLMConfig: null,
        newLLMConfig: {
            api_url: `${window.location.protocol}//${window.location.hostname}:8051`,
            provider: '',
            model: '',
            source_lang: '',
            target_lang: '',
            target_language_accent: '',
            translation_mode: 'deep_mode',
            set_as_default: true
        },
        modelFilter: '',
        configModels: [],

        // Environment Variables
        envVariables: [],
        newEnvVar: {
            key: '',
            value: '',
            description: ''
        },

        // User Glossaries
        userGlossaries: [], // List of { glossary_id, name, is_default }
        selectedGlossaryId: "none", // ID of glossary selected for translation ('', 'none', or specific ID)
        currentGlossary: { // For the create/edit form
            glossary_id: null,
            name: '',
            terms: [], // Array to hold term objects: [{ sourceTerm: '...', proposedTranslations: { 'lang': '...' } }, ...]
            glossary_json_string: '', // Store as string for textarea editing, kept in sync with terms array
        },
        newTerm: { // For the add term input fields
            source: '',
            target: ''
        },
        glossaryFilename: '', // Name of the uploaded file
        glossaryError: '', // Error message for glossary form
        glossaryUsedSource: '', // Source of glossary used in the last job ('direct', 'id', 'default', 'none')


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
                   this.apiUrl.trim() !== '' &&
                   (
                       (this.inputData.config.provider && this.inputData.config.model) || // Explicitly set
                       (this.defaultLLMConfig && this.defaultLLMConfig.provider && this.defaultLLMConfig.model) // Or default exists
                   );
        },

        // --- Methods ---
        init() {
            console.log('Alpine app initialized');
            
            // First fetch the LLM configs to get the default configuration
            this.fetchLLMConfigs().then(() => {
                // Then fetch providers to update available models
                this.fetchProviders();
            });
            
            // These can be fetched in parallel
            this.fetchJobHistory().then(() => {
                this.calculateJobStats(); // Calculate statistics after fetching job history
            });
            this.fetchEnvVariables();
            this.loadUserGlossaries(); // Fetch glossaries on init

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
            this.$watch('inputData.config.translation_mode', (val) => localStorage.setItem('translation_mode', val));

            // Set initial model list if provider/models are loaded from localStorage
            this.updateModels();
            
            // Watch for view mode changes to refresh data
            this.$watch('viewMode', (newMode) => {
                if (newMode === 'llm-config') {
                    this.fetchLLMConfigs();
                } else if (newMode === 'env-config') {
                    this.fetchEnvVariables();
                } else if (newMode === 'history') {
                    this.fetchJobHistory();
                } else if (newMode === 'glossary') {
                    this.loadUserGlossaries(); // Refresh when switching to glossary tab
                    this.resetCurrentGlossary(); // Clear edit form
                } else if (newMode === 'home') {
                    this.fetchJobHistory().then(() => {
                        this.calculateJobStats();
                    });
                }
            });

            // Apply default LLM config if available
            this.$watch('defaultLLMConfig', (config) => {
                if (config) {
                    // Always use the API URL from the default config
                    if (config.api_url) {
                        this.apiUrl = config.api_url;
                    }
                    
                    // Apply default settings if provider is empty or not set
                    if (!this.inputData.config.provider || this.inputData.config.provider.trim() === '') {
                        this.inputData.config.provider = config.provider;
                        this.inputData.config.model = config.model;
                        this.inputData.config.source_lang = config.source_lang;
                        this.inputData.config.target_lang = config.target_lang;
                        this.inputData.config.target_language_accent = config.target_language_accent;
                        if (config.translation_mode) {
                            this.inputData.config.translation_mode = config.translation_mode;
                        }
                        this.updateModels();
                    }
                }
            });

            // Watch for changes in the terms array and update the JSON string
            this.$watch('currentGlossary.terms', () => {
                this.updateGlossaryJsonString();
            }, { deep: true }); // Use deep watch for array changes
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
            console.log('Updating models for provider:', this.inputData.config.provider);
            
            // If provider is empty, try to use the default provider
            if (!this.inputData.config.provider && this.defaultLLMConfig && this.defaultLLMConfig.provider) {
                this.inputData.config.provider = this.defaultLLMConfig.provider;
                console.log('Using default provider:', this.inputData.config.provider);
            }
            
            const modelsForProvider = this.availableProviders[this.inputData.config.provider] || [];
            console.log('Raw models for provider:', modelsForProvider);
            
            if (this.modelFilter) {
                this.availableModels = modelsForProvider.filter(m => m.toLowerCase().includes(this.modelFilter.toLowerCase()));
            } else {
                this.availableModels = modelsForProvider;
            }
            
            // Check if the currently selected model is still valid
            if (!this.availableModels.includes(this.inputData.config.model)) {
                // If model is not valid, try to use the default model
                if (this.defaultLLMConfig && this.defaultLLMConfig.model &&
                    this.availableModels.includes(this.defaultLLMConfig.model)) {
                    this.inputData.config.model = this.defaultLLMConfig.model;
                    console.log('Using default model:', this.inputData.config.model);
                } else {
                    // If default model is not valid either, reset the model
                    this.inputData.config.model = '';
                    localStorage.removeItem('model');
                }
            }
            
            console.log('Filtered models:', this.availableModels);
            console.log('Selected model:', this.inputData.config.model);
        },

        handleFileUpload(event) {
            const file = event.target.files[0];
            if (file) {
                // Store the original filename
                this.originalFilename = file.name;
                
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
async startTranslation() {
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
    this.viewMode = 'form'; // Ensure we're in form view
    
    // Reset status from previous runs
    this.status = {
        current_step: 'Initializing...', progress_percent: 0, logs: [], chunks: null, translated_chunks: null, final_document: null, error_info: null, critiques: null, metrics: null
    };

    // Determine the effective configuration to send
    let configToSend = { ...this.inputData.config }; // Start with current config

    // If provider or model is missing in the current config, try using the default
    if ((!configToSend.provider || !configToSend.model) && this.defaultLLMConfig && this.defaultLLMConfig.provider && this.defaultLLMConfig.model) {
        console.log('Using default LLM config for submission:', this.defaultLLMConfig);
        configToSend.provider = this.defaultLLMConfig.provider;
        configToSend.model = this.defaultLLMConfig.model;
        // Optionally overwrite other config fields from default if they are empty in inputData?
        // Example: if (!configToSend.source_lang) configToSend.source_lang = this.defaultLLMConfig.source_lang;
        // For now, just ensuring provider and model are set from default if missing.
    } else {
         console.log('Using explicitly set config for submission:', configToSend);
    }


    const requestBody = {
        job_id: this.jobId,
        original_content: this.inputData.original_content,
        original_filename: this.originalFilename,
        config: configToSend, // Use the determined config
        glossary_id: this.selectedGlossaryId // Add selected glossary ID
    };

    try {
        // Submit job to queue
        const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/jobs`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const result = await response.json();
        console.log('Job submitted:', result);
        this.glossaryUsedSource = result.glossary_used || 'unknown'; // Store which glossary source was used

        // Connect to job stream
        this.connectToJobStream(this.jobId);
        
        // Refresh job history
        this.fetchJobHistory();
        
    } catch (error) {
        console.error("Error submitting job:", error);
        this.isLoading = false;
        this.status.error_info = "Failed to submit job: " + error.message;
    }
},

connectToJobStream(jobId) {
            if (this.eventSource) {
                this.eventSource.close();
            }
            
            const streamUrl = `${this.apiUrl.replace(/\/$/, '')}/jobs/${jobId}/stream`;
            this.sseEnded = false;
            this.eventSource = new EventSource(streamUrl);

            this.eventSource.onmessage = (event) => {
                console.log("SSE message received:", event.data);
                try {
                    const eventData = JSON.parse(event.data);
                    
                    // Update status
                    this.status.progress_percent = eventData.progress_percent || 0;
                    this.status.current_step = eventData.current_step || eventData.status || 'Processing';
                    
                    // Update chunks if available
                    if (eventData.chunks) {
                        this.status.chunks = eventData.chunks;
                    }
                    
                    // Update translated chunks if available
                    if (eventData.translated_chunks) {
                        this.status.translated_chunks = eventData.translated_chunks;
                        this.translatedChunks = eventData.translated_chunks;
                    }
                    
                    // Update job-specific extracted glossary if available (key renamed in server)
                    if (eventData.job_glossary) {
                        this.status.contextualized_glossary = eventData.job_glossary;
                    }

                    // Update critiques if available
                    if (eventData.critiques) {
                        this.status.critiques = eventData.critiques;
                    }
                    
                    // Update metrics if available
                    if (eventData.metrics) {
                        this.status.metrics = eventData.metrics;
                    }
                    
                    // Add logs if available
                    if (eventData.recent_logs) {
                        this.logs = eventData.recent_logs.map(log => `${log.created_at} [${log.level}] ${log.message}`);
                    }
                    
                    // Check for completion
                    if (eventData.final_document) {
                        this.status.final_document = eventData.final_document;
                        this.isLoading = false;
                        this.calculateDuration();
                        this.activeTab = 'full';
                        
                        // Refresh job history
                        this.fetchJobHistory();
                    }
                    
                    // Check for error
                    if (eventData.error_info) {
                        this.status.error_info = eventData.error_info;
                        this.isLoading = false;
                        this.calculateDuration();
                    }
                    
                } catch (e) {
                    console.error("Error parsing SSE message:", e);
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
        },
        
        // New methods for job history
        async fetchJobHistory() {
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/jobs`);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                this.jobHistory = data.jobs || [];
                console.log('Job history fetched:', this.jobHistory);
                return this.jobHistory;
            } catch (error) {
                console.error("Error fetching job history:", error);
                return [];
            }
        },
        
        async calculateJobStats() {
            // Reset stats
            this.jobStats = {
                totalJobs: 0,
                totalWords: 0,
                totalChars: 0,
                deepTranslationPercent: 0,
                topModels: [],
                topAccents: [],
                topLanguages: []
            };
            
            try {
                // Fetch statistics from the backend API
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/jobs/statistics`);
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const stats = await response.json();
                console.log('Job statistics fetched from API:', stats);
                
                // Map the backend stats to our frontend format
                this.jobStats = {
                    totalJobs: stats.total_jobs || 0,
                    totalWords: stats.total_words || 0,
                    totalChars: stats.total_chars || 0,
                    deepTranslationPercent: stats.deep_translation_percent || 50,
                    topModels: stats.top_models || [],
                    topAccents: stats.top_accents || [],
                    topLanguages: stats.top_languages || []
                };
                
            } catch (error) {
                console.error("Error fetching job statistics:", error);
                // Keep default values in case of error
            }
        },
        
        async fetchJobDetails(jobId) {
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/jobs/${jobId}`);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                this.selectedJob = data;
                this.viewMode = 'job-details';
                
                // Update status with job details
                this.jobId = jobId;
                this.status = {
                    current_step: data.current_step || data.status,
                    progress_percent: data.progress_percent || 0,
                    final_document: data.final_document,
                    error_info: data.error_info,
                    chunks: data.chunks || [],
                    translated_chunks: data.chunks?.map(c => c.translated_chunk) || [],
                    contextualized_glossary: data.job_glossary || [], // Use job_glossary key
                    critiques: data.critiques || [],
                    metrics: data.metrics || {}
                    // TODO: Backend should ideally return glossary_used source here too
                };
                this.glossaryUsedSource = data.glossary_used || 'unknown'; // Attempt to get from details

                // If job is still processing, connect to stream
                if (data.status === 'processing') {
                    this.isLoading = true;
                    this.connectToJobStream(jobId);
                } else {
                    this.isLoading = false;
                }
                
                console.log('Job details fetched:', data);
            } catch (error) {
                console.error("Error fetching job details:", error);
            }
        },
        
        downloadTranslation(jobId) {
            window.open(`${this.apiUrl.replace(/\/$/, '')}/jobs/${jobId}/download`, '_blank');
        },
        
        calculateDurationString(startDate, endDate) {
            const durationMs = endDate - startDate;
            const seconds = Math.floor(durationMs / 1000);
            
            if (seconds < 60) {
                return `${seconds}s`;
            }
            
            const minutes = Math.floor(seconds / 60);
            const remainingSeconds = seconds % 60;
            
            if (minutes < 60) {
                return `${minutes}m ${remainingSeconds}s`;
            }
            
            const hours = Math.floor(minutes / 60);
            const remainingMinutes = minutes % 60;
            
            return `${hours}h ${remainingMinutes}m ${remainingSeconds}s`;
        },
        
        async deleteJob(jobId) {
            if (!confirm('Are you sure you want to delete this job? This action cannot be undone.')) {
                return;
            }
            
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/jobs/${jobId}`, {
                    method: 'DELETE',
                });
                
                if (response.ok) {
                    // Remove the job from the job history
                    this.jobHistory = this.jobHistory.filter(job => job.job_id !== jobId);
                    
                    // If we're viewing the job details of the deleted job, go back to the job history
                    if (this.selectedJob && this.selectedJob.job_id === jobId) {
                        this.viewMode = 'job-history';
                    }
                } else {
                    const errorData = await response.json();
                    console.error('Error deleting job:', errorData);
                    alert(`Failed to delete job: ${errorData.detail || 'Unknown error'}`);
                }
            } catch (error) {
                console.error('Error deleting job:', error);
                alert('Failed to delete job. Please try again.');
            }
        },

        downloadJobGlossary(jobId) {
            if (!jobId) {
                console.error("No job ID provided for glossary download.");
                return;
            }
            const downloadUrl = `${this.apiUrl.replace(/\/$/, '')}/jobs/${jobId}/glossary/download`;
            console.log(`Triggering glossary download from: ${downloadUrl}`);
            // Trigger download by navigating to the endpoint
            window.location.href = downloadUrl;
        },

        showJobHistory() {
            this.viewMode = 'history';
            this.fetchJobHistory();
        },
        
        showNewTranslationForm() {
            this.viewMode = 'form';
            this.jobId = null;
            this.status = {
                current_step: null, progress_percent: 0, logs: [], chunks: null,
                translated_chunks: null, final_document: null, error_info: null
            };
        },
        
        // --- LLM Configuration Methods ---
        async fetchLLMConfigs() {
            try {
                console.log('Fetching LLM configurations...');
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/llm-configs`);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                this.llmConfigs = data.llm_configs || [];
                console.log('LLM configurations fetched:', this.llmConfigs);
                
                // Fetch default config
                await this.fetchDefaultLLMConfig();
                
                return true; // Return a value to indicate success
            } catch (error) {
                console.error("Error fetching LLM configurations:", error);
                this.llmConfigs = [];
                return false; // Return a value to indicate failure
            }
        },
        
        async fetchDefaultLLMConfig() {
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/llm-configs/default`);
                if (response.ok) {
                    this.defaultLLMConfig = await response.json();
                    console.log('Default LLM configuration fetched:', this.defaultLLMConfig);
                    
                    // Default config is fetched and stored in this.defaultLLMConfig
                    // We no longer automatically apply it to the main form here.
                    // The application logic will use this.defaultLLMConfig when needed (e.g., in startTranslation).
                } else {
                    this.defaultLLMConfig = null;
                }
            } catch (error) {
                console.error("Error fetching default LLM configuration:", error);
                this.defaultLLMConfig = null;
            }
        },
        
        updateConfigModels() {
            const modelsForProvider = this.availableProviders[this.newLLMConfig.provider] || [];
            this.configModels = modelsForProvider;
            console.log('Updated config models:', this.configModels);
        },
        
        canSaveLLMConfig() {
            return this.newLLMConfig.provider &&
                   this.newLLMConfig.model;
        },
        
        async saveLLMConfig() {
            if (!this.canSaveLLMConfig()) {
                return;
            }
            
            try {
                let response;
                let method = 'POST';
                let url = `${this.apiUrl.replace(/\/$/, '')}/llm-configs`;
                
                // If we have an ID, we're updating an existing configuration
                if (this.newLLMConfig.id) {
                    method = 'PUT';
                    url = `${url}/${this.newLLMConfig.id}`;
                }
                
                response = await fetch(url, {
                    method: method,
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(this.newLLMConfig),
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const result = await response.json();
                console.log('LLM configuration saved:', result);
                
                // Reset form
                this.newLLMConfig = {
                    api_url: `${window.location.protocol}//${window.location.hostname}:8051`,
                    provider: '',
                    model: '',
                    source_lang: '',
                    target_lang: '',
                    target_language_accent: '',
                    translation_mode: 'deep_mode',
                    set_as_default: true
                };
                
                // Refresh configurations
                await this.fetchLLMConfigs();
                
                alert('LLM configuration saved successfully!');
            } catch (error) {
                console.error("Error saving LLM configuration:", error);
                alert('Failed to save LLM configuration: ' + error.message);
            }
        },
        
        async setDefaultLLMConfig(configId) {
            try {
                const config = this.llmConfigs.find(c => c.id === configId);
                if (!config) return;
                
                const updateData = {
                    ...config,
                    set_as_default: true
                };
                
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/llm-configs/${configId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(updateData),
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                // Refresh configurations
                await this.fetchLLMConfigs();
                
                alert('Default LLM configuration updated successfully!');
            } catch (error) {
                console.error("Error updating default LLM configuration:", error);
                alert('Failed to update default LLM configuration: ' + error.message);
            }
        },
        
        async deleteLLMConfig(configId) {
            if (!confirm('Are you sure you want to delete this LLM configuration? This action cannot be undone.')) {
                return;
            }
            
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/llm-configs/${configId}`, {
                    method: 'DELETE',
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                // Refresh configurations
                await this.fetchLLMConfigs();
                
                alert('LLM configuration deleted successfully!');
            } catch (error) {
                console.error("Error deleting LLM configuration:", error);
                alert('Failed to delete LLM configuration: ' + error.message);
            }
        },
        
        // --- Environment Variables Methods ---
        async fetchEnvVariables() {
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/env-variables`);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                this.envVariables = data.env_variables || [];
                console.log('Environment variables fetched:', this.envVariables);
            } catch (error) {
                console.error("Error fetching environment variables:", error);
                this.envVariables = [];
            }
        },
        
        canSaveEnvVariable() {
            return this.newEnvVar.key && this.newEnvVar.value;
        },
        
        async saveEnvVariable() {
            if (!this.canSaveEnvVariable()) {
                return;
            }
            
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/env-variables`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(this.newEnvVar),
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const result = await response.json();
                console.log('Environment variable saved:', result);
                
                // Reset form
                this.newEnvVar = {
                    key: '',
                    value: '',
                    description: ''
                };
                
                // Refresh variables
                await this.fetchEnvVariables();
                
                alert('Environment variable saved successfully!');
            } catch (error) {
                console.error("Error saving environment variable:", error);
                alert('Failed to save environment variable: ' + error.message);
            }
        },
        
        editEnvVariable(variable) {
            this.newEnvVar = {
                key: variable.key,
                value: variable.value,
                description: variable.description || ''
            };
        },
        
        // --- LLM Configuration Edit/Duplicate Methods ---
        editLLMConfig(config) {
            // Populate the form with the selected configuration's values
            this.newLLMConfig = {
                api_url: config.api_url || `${window.location.protocol}//${window.location.hostname}:8051`,
                provider: config.provider,
                model: config.model,
                source_lang: config.source_lang,
                target_lang: config.target_lang,
                target_language_accent: config.target_language_accent || '',
                translation_mode: config.translation_mode || 'deep_mode',
                set_as_default: config.is_default,
                id: config.id // Store the ID for updating
            };
            
            // Update available models for the selected provider
            this.updateConfigModels();
            
            // Scroll to the form
            document.querySelector('.p-4.border.border-\\[var\\(--border-color\\)\\].rounded-md').scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        },
        
        duplicateLLMConfig(config) {
            // Create a new configuration with the same values but without the ID
            this.newLLMConfig = {
                api_url: config.api_url || `${window.location.protocol}//${window.location.hostname}:8051`,
                provider: config.provider,
                model: config.model,
                source_lang: config.source_lang,
                target_lang: config.target_lang,
                target_language_accent: config.target_language_accent || '',
                translation_mode: config.translation_mode || 'deep_mode',
                set_as_default: false // Don't set as default by default
            };
            
            // Update available models for the selected provider
            this.updateConfigModels();
            
            // Scroll to the form
            document.querySelector('.p-4.border.border-\\[var\\(--border-color\\)\\].rounded-md').scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        },
        
        async deleteEnvVariable(key) {
            if (!confirm('Are you sure you want to delete this environment variable? This action cannot be undone.')) {
                return;
            }
            
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/env-variables/${key}`, {
                    method: 'DELETE',
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                // Refresh variables
                await this.fetchEnvVariables();
                
                alert('Environment variable deleted successfully!');
            } catch (error) {
                console.error("Error deleting environment variable:", error);
                alert('Failed to delete environment variable: ' + error.message);
            }
        },

        // --- Glossary Management Methods ---
        async loadUserGlossaries() {
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/glossaries`);
                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                const data = await response.json();
                this.userGlossaries = data.glossaries || [];
                console.log('User glossaries loaded:', this.userGlossaries);
            } catch (error) {
                console.error("Error loading user glossaries:", error);
                this.glossaryError = `Failed to load glossaries: ${error.message}`;
                this.userGlossaries = [];
            }
        },

        // --- Glossary Management Methods ---
        determineGlossaryTargetLang() {
            // Simple approach: Use the target language from the main config.
            // TODO: Consider making this more robust, e.g., infer from existing terms or make it configurable per glossary.
            return this.inputData.config.target_lang || 'target_lang';
        },

        updateGlossaryJsonString() {
            try {
                this.currentGlossary.glossary_json_string = JSON.stringify(this.currentGlossary.terms || [], null, 2);
                this.glossaryError = ''; // Clear error if stringify succeeds
            } catch (e) {
                console.error("Error stringifying glossary terms:", e);
                this.glossaryError = "Internal error: Could not format glossary terms.";
                // Keep the old string? Or set to empty? Let's keep it for now.
            }
        },

        parseGlossaryJsonString(jsonString) {
            try {
                const parsed = JSON.parse(jsonString || '[]');
                if (Array.isArray(parsed)) {
                    const targetLang = this.determineGlossaryTargetLang(); // Get the target language
                    // Map the parsed terms to the structure used internally { sourceTerm: '...', proposedTranslations: { 'lang': '...' } }
                    // The UI rendering logic will handle displaying the correct translation based on targetLang
                    this.currentGlossary.terms = parsed.map(term => {
                        if (term && typeof term.sourceTerm === 'string' && typeof term.proposedTranslations === 'object' && term.proposedTranslations !== null) {
                            // Ensure proposedTranslations is always an object, even if empty in the file
                            const translations = term.proposedTranslations || {};
                            // Return the standard internal structure
                            return {
                                sourceTerm: term.sourceTerm,
                                proposedTranslations: translations
                            };
                        }
                        return null; // Filter out invalid entries later
                    }).filter(term => term !== null); // Remove null entries from invalid items

                    this.glossaryError = ''; // Clear error on success
                } else {
                    throw new Error("JSON is not an array.");
                }
            } catch (e) {
                console.error("Error parsing glossary JSON:", e);
                this.glossaryError = `Invalid JSON format: ${e.message}. Please check the structure.`;
                this.currentGlossary.terms = []; // Reset terms on error
            }
        },

        addGlossaryTerm() {
            if (!this.newTerm.source || !this.newTerm.target) {
                this.glossaryError = "Both source and target terms are required.";
                return;
            }
            const targetLang = this.determineGlossaryTargetLang();
            const newEntry = {
                sourceTerm: this.newTerm.source.trim(),
                proposedTranslations: {
                    "default": this.newTerm.target.trim() // Always use "default" as the key
                }
            };

            // Ensure terms array exists before checking for duplicates
            if (!Array.isArray(this.currentGlossary.terms)) {
                console.error("Error: currentGlossary.terms is not an array! Initializing.", this.currentGlossary);
                this.glossaryError = "Internal error: Glossary data structure invalid. Initializing.";
                this.currentGlossary.terms = []; // Initialize as fallback
            }

            // Avoid adding duplicates (simple check based on sourceTerm)
            if (this.currentGlossary.terms.some(term => term.sourceTerm === newEntry.sourceTerm)) {
                 this.glossaryError = `Source term "${newEntry.sourceTerm}" already exists.`;
                 return;
            }

            // Check again if terms is an array before pushing
            if (Array.isArray(this.currentGlossary.terms)) {
                 this.currentGlossary.terms.push(newEntry);
                 // The watcher will call updateGlossaryJsonString automatically
            } else {
                 console.error("Error: Failed to push to currentGlossary.terms as it's still not an array.");
                 this.glossaryError = "Internal error: Could not add term.";
                 return; // Prevent further issues
            }

            // Clear input fields
            this.newTerm.source = '';
            this.newTerm.target = '';
            this.glossaryError = ''; // Clear any previous error
        },

        removeGlossaryTerm(index) {
            if (index >= 0 && index < this.currentGlossary.terms.length) {
                this.currentGlossary.terms.splice(index, 1);
                // The watcher will call updateGlossaryJsonString automatically
            }
        },

        handleGlossaryFileUpload(event) {
            const file = event.target.files[0];
            if (file) {
                this.glossaryFilename = file.name;
                const reader = new FileReader();
                reader.onload = (e) => {
                    const jsonString = e.target.result;
                    this.currentGlossary.glossary_json_string = jsonString; // Store the raw string first
                    this.parseGlossaryJsonString(jsonString); // Attempt to parse into the terms array
                    // If parsing fails, parseGlossaryJsonString will set the error and clear terms
                };
                reader.onerror = (e) => {
                    console.error("Error reading glossary file:", e);
                    this.glossaryError = "Error reading file.";
                    this.glossaryFilename = '';
                    this.currentGlossary.terms = []; // Ensure terms is reset on error
                    this.currentGlossary.glossary_json_string = ''; // Clear string on error
                };
                reader.readAsText(file);
            }
        },

        resetCurrentGlossary() {
            this.currentGlossary = {
                glossary_id: null,
                name: '',
                terms: [], // Reset terms array
                glossary_json_string: '[]', // Reset JSON string
            };
            this.newTerm = { source: '', target: '' }; // Reset input fields
            this.glossaryFilename = '';
            this.glossaryError = '';
            // Reset file input visually
            const fileInput = document.getElementById('glossary-file-upload');
            if (fileInput) fileInput.value = null;
            // No need to call updateGlossaryJsonString, watcher handles it if terms change, or it's set directly
        },

        async saveUserGlossary() {
            this.glossaryError = ''; // Clear previous errors
            let parsedGlossaryData;

            // 1. Parse and Validate JSON string
            // We will now use the terms array directly
            if (!this.currentGlossary.name || !this.currentGlossary.name.trim()) {
                this.glossaryError = "Glossary name cannot be empty.";
                return;
            }
            if (!Array.isArray(this.currentGlossary.terms) || this.currentGlossary.terms.length === 0) {
                this.glossaryError = "Glossary must contain at least one term.";
                return;
            }
            // Basic validation could be added here if needed, but the add/remove functions should maintain structure.
            parsedGlossaryData = this.currentGlossary.terms; // Use the terms array directly

            // 2. Prepare request data
            const glossaryPayload = {
                name: this.currentGlossary.name,
                glossary_data: parsedGlossaryData
            };

            // 3. Determine URL and Method (Create vs Update)
            const isUpdate = !!this.currentGlossary.glossary_id;
            const url = isUpdate
                ? `${this.apiUrl.replace(/\/$/, '')}/glossaries/${this.currentGlossary.glossary_id}`
                : `${this.apiUrl.replace(/\/$/, '')}/glossaries`;
            const method = isUpdate ? 'PUT' : 'POST';

            // 4. Send request
            try {
                const response = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(glossaryPayload)
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.detail || `HTTP error! status: ${response.status}`);
                }

                alert(`Glossary '${glossaryPayload.name}' ${isUpdate ? 'updated' : 'saved'} successfully!`);
                this.resetCurrentGlossary();
                await this.loadUserGlossaries(); // Refresh the list

            } catch (error) {
                console.error(`Error ${isUpdate ? 'updating' : 'saving'} glossary:`, error);
                this.glossaryError = `Failed to ${isUpdate ? 'update' : 'save'} glossary: ${error.message}`;
            }
        },

        async editUserGlossary(glossaryId) {
            this.glossaryError = '';
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/glossaries/${glossaryId}`);
                if (!response.ok) {
                     const errData = await response.json();
                    throw new Error(errData.detail || `HTTP error! status: ${response.status}`);
                }
                const glossaryData = await response.json();

                this.currentGlossary = {
                    glossary_id: glossaryData.glossary_id,
                    name: glossaryData.name,
                    terms: glossaryData.glossary_data || [], // Populate the terms array for the UI
                    // Pretty-print JSON for editing
                    glossary_json_string: JSON.stringify(glossaryData.glossary_data || [], null, 2)
                };
                this.glossaryFilename = ''; // Clear filename when editing

                // Scroll to the form for better UX
                 document.querySelector('.card h3[x-text^="Edit Glossary"]').scrollIntoView({ behavior: 'smooth' });


            } catch (error) {
                console.error(`Error fetching glossary ${glossaryId} for editing:`, error);
                this.glossaryError = `Failed to load glossary for editing: ${error.message}`;
            }
        },

        async deleteUserGlossary(glossaryId, glossaryName) {
            if (!confirm(`Are you sure you want to delete the glossary "${glossaryName}"? This cannot be undone.`)) return;
            this.glossaryError = '';
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/glossaries/${glossaryId}`, { method: 'DELETE' });
                 const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.detail || `HTTP error! status: ${response.status}`);
                }
                alert(`Glossary "${glossaryName}" deleted successfully.`);
                await this.loadUserGlossaries(); // Refresh list
                 // If the deleted glossary was being edited, reset the form
                if (this.currentGlossary.glossary_id === glossaryId) {
                    this.resetCurrentGlossary();
                }
            } catch (error) {
                console.error(`Error deleting glossary ${glossaryId}:`, error);
                 this.glossaryError = `Failed to delete glossary: ${error.message}`;
                 // Still try to refresh list in case of partial failure or stale data
                 await this.loadUserGlossaries();
            }
        },

        async setDefaultUserGlossary(glossaryId) {
             this.glossaryError = '';
            try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/glossaries/${glossaryId}/default`, { method: 'POST' });
                 const result = await response.json();
                if (!response.ok) {
                     throw new Error(result.detail || `HTTP error! status: ${response.status}`);
                }
                alert(`Glossary set as default successfully.`);
                await this.loadUserGlossaries(); // Refresh list to show new default status
            } catch (error) {
                console.error(`Error setting glossary ${glossaryId} as default:`, error);
                 this.glossaryError = `Failed to set default glossary: ${error.message}`;
                 // Still try to refresh list
                 await this.loadUserGlossaries();
            }
        },

        async downloadGlossary(glossaryId, glossaryName) {
             this.glossaryError = '';
             try {
                const response = await fetch(`${this.apiUrl.replace(/\/$/, '')}/glossaries/${glossaryId}`);
                 if (!response.ok) {
                     const errData = await response.json();
                    throw new Error(errData.detail || `HTTP error! status: ${response.status}`);
                }
                const glossary = await response.json();
                const jsonString = JSON.stringify(glossary.glossary_data || [], null, 2);
                const filename = `${glossaryName.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_glossary.json`;
                this.downloadFile(jsonString, filename, 'application/json');

            } catch (error) {
                console.error(`Error downloading glossary ${glossaryId}:`, error);
                 this.glossaryError = `Failed to download glossary: ${error.message}`;
            }
        }

    }));
});
