#include<stdio.h>
#include<stdlib.h>
int main()
{
    FILE *fp;
    char s;
    fp=fopen("b.txt","r");
    char c=fgetc(fp);
    printf("%c",c);
    printf("\n");
    printf("%d",ftell(fp));
    printf("\n");
    fseek(fp,0,SEEK_END);
    printf("%d",ftell(fp));
    fscanf(fp,"%s",s);
    printf("%s",s);
    printf("\n");
    printf("%d",ftell(fp));
    fclose(fp);
}