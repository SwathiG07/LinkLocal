#include<stdio.h>
#include<string.h>
int main()
{
FILE *fp;
fp=fopen("a.txt","w");
char s[10]="hello";
for(int i=0;i!=strlen(s);i++)
{
fputc(s[i],fp);
}
printf("\n");
fputs(s,fp);
fclose(fp);
return 0;
}