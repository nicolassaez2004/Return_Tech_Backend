# Return Tech — editor, execução e correção por código

Esta atualização conecta a interface React ao Judge0 por meio do Flask. O candidato escreve o programa no site, experimenta entradas e envia a solução para correção automática. Os programas são executados pelo Judge0; o Flask recebe os resultados e registra a pontuação no MongoDB.

## 1. Atualizar os projetos

Esta revisão usa somente um arquivo `.env` existente em cada projeto. O `.env` do backend mantém os valores de MongoDB, JWT e as demais configurações recebidas, com as variáveis do Judge0 acrescentadas ao final. O `.env` do frontend contém apenas o endereço público da API (`VITE_API_URL`); as configurações de Flask, MongoDB e JWT foram retiradas dele.

Os ZIPs desta revisão são uma devolução privada e incluem esses `.env`. Não publique os ZIPs nem os arquivos `.env` no GitHub. Histórico Git, ambientes virtuais, `node_modules` e arquivos de build não estão incluídos. O `.gitignore` continua protegendo `.env` e suas variantes.

Copie os arquivos atualizados para as respectivas pastas dos projetos, mantendo seu `.git`, sua branch e as dependências locais. Se você alterou seu `.env` depois de enviar os ZIPs, mantenha seus valores mais recentes e acrescente somente as variáveis ausentes. Exclua apenas o antigo `.env.example` de cada pasta, caso ele ainda esteja no seu computador. Não renomeie nem copie o modelo por cima do `.env` original.

O backend carrega explicitamente o `.env` que está na mesma pasta de `run.py`, mesmo que seja iniciado de outro diretório. Variáveis já definidas pelo ambiente de hospedagem continuam tendo prioridade. O Vite usa o `.env` do próprio frontend. Nenhum processo lê o `.env` do outro projeto.

No backend, instale as dependências atualizadas:

```powershell
python -m pip install -r requirements.txt
```

No frontend, reinstale a partir do lockfile:

```powershell
npm ci
```

Use Python 3.11 ou superior e Node.js 22.12 ou superior. A dependência `tzdata` permite interpretar o prazo no Windows. O editor Monaco é empacotado com a aplicação e carregado apenas ao abrir o editor.

## 2. Configurar o Judge0

Obtenha uma conta/plano de execução na modalidade em nuvem indicada no site oficial: https://judge0.com/. Esta entrega não cria conta nem contrata um plano.

Abra o mesmo `.env` **do backend** que já contém a conexão MongoDB e a chave JWT. As linhas abaixo já foram acrescentadas nesta revisão. Preencha os campos aplicáveis ao seu provedor com os valores reais, sem repetir as linhas nem substituir as demais configurações:

```env
JUDGE0_URL=
JUDGE0_API_KEY=
JUDGE0_RAPIDAPI_HOST=
JUDGE0_AUTH_TOKEN=
```

- `JUDGE0_URL`: URL base real da API, sem `/submissions` e sem os parâmetros da requisição. Não há um endereço ou uma chave de acesso inventados nesta entrega.
- `JUDGE0_API_KEY`: chave enviada em `X-RapidAPI-Key` quando o provedor usa RapidAPI/API Hub.
- `JUDGE0_RAPIDAPI_HOST`: valor de `X-RapidAPI-Host`, quando exigido pelo provedor.
- `JUDGE0_AUTH_TOKEN`: alternativa para uma instância direta que exija `X-Auth-Token`. Não é preciso preencher as opções de RapidAPI nesse caso.

A integração usa a API compatível com Judge0 CE: `GET /languages`, `POST /submissions/batch` e `GET /submissions/batch`. Confirme que seu plano permite esses endpoints. Cada teste privado gera uma execução: uma solução corrigida contra cinco testes usa cinco submissões, além de consultas de estado. Considere isso na escolha da cota.

A chave fica somente no servidor. Não crie variáveis `VITE_` para segredos. O `.env` existente do frontend usa apenas:

```env
VITE_API_URL=http://localhost:5000/api
```

Esse endereço aponta para o Flask local, e não para o Judge0. Se o Flask estiver em outro endereço, atualize essa mesma linha. Não copie MongoDB, JWT ou credenciais do Judge0 para o frontend. Use HTTPS para um executor remoto. HTTP é aceito apenas em localhost para desenvolvimento.

Se `JUDGE0_URL` estiver vazio, os botões **Executar** e **Enviar solução** ficam desabilitados, mas o rascunho continua editável. Isso significa configuração pendente, sem uma execução em andamento. O cursor de espera aparece somente enquanto uma solicitação ou execução está em andamento; o aviso explica quando o serviço ainda não foi configurado. Nenhuma nota é inventada.

Após editar o `.env` do backend, reinicie tanto o Flask quanto o processo `process-code-jobs --watch`. Depois de editar o `.env` do frontend, reinicie o Vite. Feche e reabra o editor no site para carregar o estado atualizado.

## 3. Iniciar

Execute o backend e o frontend como já eram executados:

```powershell
# Terminal do backend, com seu ambiente virtual ativo
python run.py
```

```powershell
# Terminal do frontend
npm run dev
```

O backend cria os índices das novas coleções na inicialização. Não é necessário migrar os documentos antigos.

Em um terceiro terminal com o ambiente virtual do backend, execute o processo de consulta da fila:

```powershell
python -m flask --app run process-code-jobs --watch
```

Esse processo deve permanecer ativo no ambiente publicado para concluir correções mesmo quando o candidato fecha o navegador. A tela também consulta o andamento enquanto está aberta. Para consultar a fila uma única vez, omita `--watch`. Em produção, execute esse comando como um processo supervisionado separado do servidor web.

## 4. Testar a demonstração com a API real

1. Entre como empresa.
2. Abra **Publicar desafio** e clique em **Criar demonstração**.
3. O sistema cria um rascunho com enunciado, exemplo e cinco testes privados.
4. Clique em **Configurar código** se quiser inspecionar os testes. Publique o rascunho.
5. Entre como candidato em outro navegador/janela anônima e participe do desafio.
6. Clique em **Abrir editor**.
7. Escreva a solução abaixo e clique em **Executar**. O exemplo deve imprimir `2`.
8. Após o breve intervalo entre execuções, clique em **Enviar solução**. Todos os cinco testes devem passar e a pontuação deve ser **100/100**.
9. Reenvie a solução: a melhor pontuação continua em 100, sem somar novamente.
10. Volte à empresa e abra **Código e pontos**. O candidato deve aparecer uma vez, com sua melhor pontuação e o código do último envio para correção.

```python
import sys

linhas = sys.stdin.read().splitlines()
print(sum(linha == "FAIL" for linha in linhas))
```

Confira também os casos de falha:

| Código | Resultado esperado |
|---|---|
| `print(999)` | Resposta incorreta; 0 pontos naquela tentativa |
| `print(` | Erro de compilação ou execução, conforme a linguagem |
| `while True: pass` | Tempo excedido |
| Serviço indisponível ou erro interno do executor | Tentativa pendente ou sem nota; a melhor pontuação anterior é mantida |

Os rascunhos do editor ficam no `sessionStorage` do navegador, separados por candidato, desafio e linguagem. Eles sobrevivem a um recarregamento da aba, mas não são um backup permanente. A melhor pontuação fica no MongoDB. Desafios encerrados permanecem na aba de participações de quem já se inscreveu.

## 5. Receber os desafios da equipe responsável

Sua integração pode ser entregue com a demonstração. Os desafios definitivos precisam seguir o contrato de entrada e saída padrão: o programa lê `stdin` e imprime o resultado em `stdout`.

A empresa cria o desafio normalmente e, enquanto ele for um rascunho, usa **Configurar código** para cadastrar este JSON:

```json
{
  "languages": ["python"],
  "max_points": 100,
  "cpu_time_limit": 2,
  "memory_limit_kb": 128000,
  "example": {
    "stdin": "2 3\n",
    "expected_output": "5\n"
  },
  "starter_code": {
    "python": "# Leia dois números da entrada e imprima a soma.\n"
  },
  "tests": [
    { "stdin": "1 1\n", "expected_output": "2\n" },
    { "stdin": "-5 2\n", "expected_output": "-3\n" }
  ]
}
```

- `example` e `starter_code` aparecem para os candidatos.
- `tests` fica em uma coleção separada, acessível somente à empresa proprietária pelas rotas de configuração.
- Cadastre de 1 a 20 testes; entrada e saída de cada caso podem ter até 16 KB.
- `languages` aceita `python`, `javascript` e `cpp`. A API consulta os IDs reais de Python 3, Node.js e GCC disponíveis no provedor. O código inicial de cada linguagem é opcional.
- `max_points` é um inteiro entre 1 e 10.000. Todos os testes precisam passar para conquistar os pontos. Nesta versão não há pontuação parcial.
- O limite de CPU pode variar de 0,5 a 5 segundos por teste; memória entre 64.000 e 256.000 KB.
- O código do candidato tem limite de 64 KB. A execução não recebe acesso de rede e usa limites de arquivos, tempo e processos.
- A configuração fica bloqueada após a publicação e não pode mudar quando já existem tentativas. Para outro conjunto de testes, crie outro desafio.
- O prazo informado como data termina no final daquele dia no fuso de São Paulo. O backend verifica o prazo antes de cada execução ou correção.

Os testes precisam verificar o comportamento esperado; a API não deduz a intenção do enunciado nem avalia sozinha qualidade ou segurança do código. Bibliotecas instaladas e versões de linguagem dependem do executor. A demonstração inicial usa Python.

## 6. Pontuação e avaliação humana

O resultado automático é separado das submissões de relatórios e das avaliações humanas. Uma nota de código não adiciona o candidato automaticamente à shortlist e não sobrescreve uma decisão da empresa.

A melhor pontuação é mantida com uma atualização atômica `$max`, por candidato e desafio. Consultar a mesma execução várias vezes, reenviar uma resposta correta ou concluir uma tentativa incorreta depois de uma correta não aumenta nem reduz os pontos já conquistados.

Falhas de comunicação preservam o trabalho pendente para nova consulta. Erros internos do executor não recebem nota. Após cinco minutos sem conclusão, a tentativa fica como falha do serviço e permite novo envio. Apenas uma execução pode ficar ativa por candidato/desafio; novos envios têm um intervalo mínimo de três segundos.

As saídas dos testes privados não são solicitadas ao executor e não são retornadas à interface. O candidato recebe o status de cada teste, a quantidade de acertos e a pontuação. Em **Executar**, a entrada foi escolhida pelo próprio candidato, por isso a saída e os erros desse teste são exibidos.

## 7. Arquivos e rotas adicionados

Backend:

- `app/services/judge0.py`: adaptador HTTP e descoberta das linguagens.
- `app/services/coding.py`: validação, estados da execução e pontuação.
- `app/routes/coding.py`: rotas de configuração, execução, consulta e resultados.
- `app/coding_setup.py`: índices e processo de consulta da fila.
- Coleções novas: `coding_configs`, `coding_jobs`, `coding_scores`.

Frontend:

- `src/coding/CodeEditor.jsx`: Monaco e worker empacotados localmente.
- `src/coding/CodingWorkspace.jsx`: escrita, execução, envio e consulta de resultados.
- `src/coding/CodingSettings.jsx`: configuração privada pela empresa.
- `src/coding/CodingResults.jsx`: pontuação dos candidatos para a empresa.
- `src/coding/coding.css`: apresentação e adaptação para telas menores.

| Método e rota | Acesso |
|---|---|
| `GET /api/challenges/<id>/coding` | Candidato inscrito ou empresa proprietária; sem testes privados |
| `GET/PUT /api/challenges/<id>/coding/config` | Empresa proprietária; gravação apenas em rascunho sem tentativas |
| `POST /api/challenges/<id>/code-jobs` | Candidato inscrito, desafio publicado e dentro do prazo |
| `GET /api/code-jobs/<id>` | Dono da tentativa ou empresa proprietária do desafio |
| `GET /api/challenges/<id>/coding/results` | Empresa proprietária |
| `POST /api/coding/demo` | Empresa; cria uma demonstração em rascunho |

Exemplo de envio para a API do Return Tech:

```json
{
  "mode": "submit",
  "language": "python",
  "source_code": "print(2)"
}
```

Use `mode: "run"` e um campo `stdin` para uma execução experimental. A criação responde com HTTP 202 e um `job._id`. Consulte a rota de execução até o estado `completed` ou `service_error`. As chaves e tokens internos do provedor não são expostos. O corpo enviado pelo candidato não controla testes privados, pontos ou limites do executor.

## 8. Verificação realizada e limites

Os testes automatizados usam MongoDB simulado e respostas simuladas de Judge0. Nenhum programa de candidato é executado localmente nesses testes.

```powershell
# Backend
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

```powershell
# Frontend
npm ci
npm test
npm run build
```

A suíte cobre isolamento entre empresas/candidatos, ocultação de testes e saídas privadas, concessão de pontos sem duplicidade, erros de programa e do executor, expiração, limites, recuperação de fila e interações da interface. Os testes de interface usam um substituto do editor Monaco; o código real do Monaco é verificado pelo build.

A validação visual em um navegador real não pôde ser concluída neste ambiente. A execução contra uma conta real do Judge0 e o MongoDB da equipe também precisam ser homologados com as configurações locais de vocês, seguindo o roteiro da seção 4. O build emite um aviso pelo tamanho do Monaco, que é carregado sob demanda.

Documentação oficial: https://ce.judge0.com/ e https://github.com/microsoft/monaco-editor.
