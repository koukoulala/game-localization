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
        viewMode: 'form', // 'form', 'history', 'job-details', 'llm-config', 'env-config'
        
        // LLM Configuration
        llmConfigs: [],
        defaultLLMConfig: null,
        newLLMConfig: {
            api_url: 'http://localhost:8051',
            provider: '',
            model: '',
            source_lang: '',
            target_lang: '',
            target_language_accent: '',
            set_as_default: true
        },
        configModels: [],
        
        // Environment Variables
        envVariables: [],
        newEnvVar: {
            key: '',
            value: '',
            description: ''
        },


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
            
            // First fetch the LLM configs to get the default configuration
            this.fetchLLMConfigs().then(() => {
                // Then fetch providers to update available models
                this.fetchProviders();
            });
            
            // These can be fetched in parallel
            this.fetchJobHistory();
            this.fetchEnvVariables();

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
            
            // Watch for view mode changes to refresh data
            this.$watch('viewMode', (newMode) => {
                if (newMode === 'llm-config') {
                    this.fetchLLMConfigs();
                } else if (newMode === 'env-config') {
                    this.fetchEnvVariables();
                } else if (newMode === 'history') {
                    this.fetchJobHistory();
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
                        this.updateModels();
                    }
                }
            });
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

    const requestBody = {
        job_id: this.jobId,
        original_content: this.inputData.original_content,
        original_filename: this.originalFilename,
        config: this.inputData.config
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
                    
                    // Update glossary if available
                    if (eventData.glossary) {
                        this.status.contextualized_glossary = eventData.glossary;
                    } else if (eventData.contextualized_glossary) {
                        this.status.contextualized_glossary = eventData.contextualized_glossary;
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
            } catch (error) {
                console.error("Error fetching job history:", error);
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
                    contextualized_glossary: data.glossary || [],
                    critiques: data.critiques || [],
                    metrics: data.metrics || {}
                };
                
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
                    
                    // Directly apply the default configuration
                    if (this.defaultLLMConfig) {
                        // Always use the API URL from the default config
                        if (this.defaultLLMConfig.api_url) {
                            this.apiUrl = this.defaultLLMConfig.api_url;
                        }
                        
                        // Apply provider and model from default config if not already set
                        if (!this.inputData.config.provider || this.inputData.config.provider.trim() === '') {
                            this.inputData.config.provider = this.defaultLLMConfig.provider;
                        }
                        
                        if (!this.inputData.config.model || this.inputData.config.model.trim() === '') {
                            this.inputData.config.model = this.defaultLLMConfig.model;
                        }
                        
                        // Apply language settings from default config
                        this.inputData.config.source_lang = this.defaultLLMConfig.source_lang || this.inputData.config.source_lang;
                        this.inputData.config.target_lang = this.defaultLLMConfig.target_lang || this.inputData.config.target_lang;
                        this.inputData.config.target_language_accent = this.defaultLLMConfig.target_language_accent || this.inputData.config.target_language_accent;
                        
                        // Update available models based on the provider
                        this.updateModels();
                    }
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
                   this.newLLMConfig.model &&
                   this.newLLMConfig.source_lang &&
                   this.newLLMConfig.target_lang;
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
                    api_url: 'http://localhost:8051',
                    provider: '',
                    model: '',
                    source_lang: '',
                    target_lang: '',
                    target_language_accent: '',
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
                api_url: config.api_url || 'http://localhost:8051',
                provider: config.provider,
                model: config.model,
                source_lang: config.source_lang,
                target_lang: config.target_lang,
                target_language_accent: config.target_language_accent || '',
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
                api_url: config.api_url || 'http://localhost:8051',
                provider: config.provider,
                model: config.model,
                source_lang: config.source_lang,
                target_lang: config.target_lang,
                target_language_accent: config.target_language_accent || '',
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
        }

    }));
});